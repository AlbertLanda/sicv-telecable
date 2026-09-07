"""Ajustes del tablero de programación sin convertirlo en despacho.

El flujo operativo confirmado separa dos cosas:

- programar/reprogramar = decidir cuándo se espera atender una OT;
- tomar una OT = el técnico se la adjudica desde la API técnica.

Una OT PENDING puede por tanto cambiar de fecha aunque todavía no tenga
`assigned_technician`. En ese caso se conserva PENDING y la trazabilidad vive
en WorkOrderReprogramming. Para órdenes ya asignadas o en atención se mantiene
el comportamiento histórico de WorkOrder.reprogram().
"""

import json
from datetime import datetime, time
from sqlite3 import SQLITE_BUSY, SQLITE_LOCKED

from django.core.exceptions import ValidationError
from django.db import OperationalError, transaction
from django.http import JsonResponse
from django.utils import formats, timezone
from django.views import View

from apps.work_orders import views as legacy_views
from apps.work_orders.forms import WorkOrderRescheduleForm
from apps.work_orders.models import WorkOrder, WorkOrderReprogramming
from apps.work_orders.views import (
    WorkOrderScheduleBoardView as LegacyScheduleBoardView,
    _open_orders_for_schedule,
    _schedule_stats,
    _schedule_week,
)


class WorkOrderScheduleBoardView(LegacyScheduleBoardView):
    """Tablero semanal que también permite mover OT todavía PENDING.

    La vista base ya resuelve sede, semana, columnas, estadísticas y permisos.
    Aquí solo ampliamos el conjunto que la interfaz puede arrastrar: una orden
    pendiente sigue siendo trabajo programable aunque aún no tenga técnico.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        statuses = list(context["reschedulable_statuses"])
        if WorkOrder.Status.PENDING not in statuses:
            statuses.insert(0, WorkOrder.Status.PENDING)
        context["reschedulable_statuses"] = statuses
        return context


class WorkOrderRescheduleView(View):
    """Mueve una OT a otro día sin forzar una asignación de técnico.

    Para PENDING se acepta programar con hora o solo con día -"día
    acordado, sin hora"-: si no llega una hora explícita y la orden no
    tenía ninguna previa, se guarda únicamente el día (scheduled_date) en
    vez de inventar una. El estado sigue siendo PENDING y no se toca
    assigned_technician.

    Programar es una capacidad distinta de asignar técnico. El endpoint exige
    `work_orders.schedule_workorder`; el rol ATC recibe esa capacidad como
    permiso base desde accounts.User, sin recibir `assign_workorder`.
    """

    def post(self, request, pk):
        if not request.user.has_perm("work_orders.schedule_workorder"):
            return JsonResponse(
                {
                    "ok": False,
                    "message": "No tiene permiso para programar o reprogramar órdenes de trabajo.",
                },
                status=403,
            )

        try:
            payload = json.loads(request.body or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse(
                {"ok": False, "message": "Solicitud inválida."},
                status=400,
            )

        if (
            not isinstance(payload, dict)
            or any(
                not isinstance(payload.get(field, ""), str)
                for field in ("date", "reason")
            )
            or ("time" in payload and not isinstance(payload["time"], str))
        ):
            return JsonResponse(
                {
                    "ok": False,
                    "message": "Solicitud inválida: fecha, hora y motivo deben ser texto.",
                },
                status=400,
            )

        # La reprogramación es una acción auditada: no se acepta un cambio de
        # compromiso sin explicar por qué. Así el historial puede responder
        # quién cambió la OT, cuándo lo hizo y por qué.
        reason = payload.get("reason", "").strip()
        if not reason:
            return JsonResponse(
                {
                    "ok": False,
                    "message": "Debe indicar el motivo de la programación o reprogramación.",
                },
                status=400,
            )
        payload["reason"] = reason

        form = WorkOrderRescheduleForm(payload)
        if not form.is_valid():
            return JsonResponse(
                {
                    "ok": False,
                    "message": " ".join(
                        message
                        for errors in form.errors.values()
                        for message in errors
                    ),
                },
                status=400,
            )

        try:
            with transaction.atomic():
                order = legacy_views.get_object_or_404(
                    WorkOrder.objects.select_for_update(of=("self",)),
                    pk=pk,
                )
                new_scheduled_at, new_scheduled_date = self._resolve_schedule(
                    order,
                    form.cleaned_data["date"],
                    form.cleaned_data.get("time"),
                )

                if order.status == WorkOrder.Status.PENDING:
                    reprogramming = self._schedule_pending(
                        order,
                        new_scheduled_at,
                        new_scheduled_date,
                        request.user,
                        reason,
                    )
                else:
                    reprogramming = order.reprogram(
                        new_schedule=new_scheduled_at,
                        new_schedule_date=new_scheduled_date,
                        user=request.user,
                        reason=reason,
                    )

        except ValidationError as exc:
            return JsonResponse(
                {"ok": False, "message": " ".join(exc.messages)},
                status=400,
            )

        except OperationalError as exc:
            error_code = getattr(exc.__cause__, "sqlite_errorcode", None)
            if (
                error_code is None
                or error_code & 0xFF not in (SQLITE_BUSY, SQLITE_LOCKED)
            ):
                raise
            return JsonResponse(
                {
                    "ok": False,
                    "message": (
                        "Otra operación está actualizando las órdenes. "
                        "Actualice el tablero y vuelva a intentarlo."
                    ),
                },
                status=409,
            )

        order.refresh_from_db()
        agenda_date = order.agenda_date

        return JsonResponse(
            {
                "ok": True,
                "order_number": order.order_number,
                "status": order.status,
                "status_display": order.get_status_display(),
                "scheduled_at": (
                    timezone.localtime(order.scheduled_at).isoformat()
                    if order.scheduled_at
                    else None
                ),
                "date": agenda_date.isoformat(),
                "reprogramming_id": reprogramming.pk,
                "stats": _schedule_stats(
                    _open_orders_for_schedule(request),
                    _schedule_week(request),
                    timezone.localdate(),
                ),
                "message": (
                    f"Orden {order.order_number} programada para el "
                    f"{formats.date_format(agenda_date, 'j N')}."
                ),
            }
        )

    @staticmethod
    def _resolve_schedule(order, new_date, submitted_time):
        """Decide si el nuevo compromiso lleva hora o es solo día.

        - Si llega una hora explícita, se usa esa.
        - Si no llega hora pero la orden ya tenía una (scheduled_at), se
          conserva: arrastrar una tarjeta cambia el día, no la hora.
        - Si no hay hora ni previa ni nueva, el compromiso es solo de día:
          no se inventa ninguna.

        Devuelve (scheduled_at, scheduled_date): exactamente uno de los
        dos queda con valor, el otro en None.
        """
        if submitted_time is not None:
            time_of_day = submitted_time
        elif order.scheduled_at is not None:
            time_of_day = timezone.localtime(order.scheduled_at).time()
        else:
            time_of_day = None

        if time_of_day is None:
            return None, new_date

        naive = datetime.combine(new_date, time_of_day)
        return timezone.make_aware(naive, timezone.get_current_timezone()), None

    @staticmethod
    def _schedule_pending(order, new_scheduled_at, new_scheduled_date, user, reason):
        """Cambia agenda de una PENDING y conserva su estado operativo."""
        if not reason or not reason.strip():
            raise ValidationError(
                {"reason": "Debe indicar el motivo de la programación o reprogramación."}
            )

        previous_schedule = order.scheduled_at
        previous_schedule_date = order.scheduled_date

        if (
            new_scheduled_at is not None
            and previous_schedule
            and new_scheduled_at == previous_schedule
        ):
            raise ValidationError(
                {
                    "scheduled_at": (
                        "La nueva fecha debe ser diferente "
                        "a la fecha programada actual."
                    )
                }
            )

        if (
            new_scheduled_date is not None
            and previous_schedule is None
            and previous_schedule_date == new_scheduled_date
        ):
            raise ValidationError(
                {
                    "scheduled_date": (
                        "El nuevo día debe ser diferente "
                        "al día programado actual."
                    )
                }
            )

        if new_scheduled_at is not None and new_scheduled_at <= timezone.now():
            raise ValidationError(
                {
                    "scheduled_at": (
                        "La nueva fecha de atención debe ser futura."
                    )
                }
            )

        if new_scheduled_date is not None and new_scheduled_date < timezone.localdate():
            raise ValidationError(
                {
                    "scheduled_date": (
                        "El nuevo día de atención debe ser hoy "
                        "o una fecha futura."
                    )
                }
            )

        now = timezone.now()
        updated = WorkOrder.objects.filter(
            pk=order.pk,
            status=WorkOrder.Status.PENDING,
            scheduled_at=previous_schedule,
            scheduled_date=previous_schedule_date,
        ).update(
            scheduled_at=new_scheduled_at,
            scheduled_date=new_scheduled_date,
            updated_at=now,
        )
        if not updated:
            raise ValidationError(
                {
                    "status": (
                        "La orden cambió mientras se procesaba la solicitud. "
                        "Actualice el tablero antes de volver a intentarlo."
                    )
                }
            )

        order.scheduled_at = new_scheduled_at
        order.scheduled_date = new_scheduled_date
        order.updated_at = now

        return WorkOrderReprogramming.objects.create(
            work_order=order,
            previous_schedule=previous_schedule,
            previous_schedule_date=previous_schedule_date,
            new_schedule=new_scheduled_at,
            new_schedule_date=new_scheduled_date,
            reason=reason.strip(),
            created_by=user,
        )