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

    Para PENDING se actualiza únicamente la agenda y se registra
    WorkOrderReprogramming; el estado sigue siendo PENDING. Para los estados
    que ya soportaban la transición a REPROGRAMMED se delega en el método de
    dominio existente, preservando compatibilidad con el flujo probado.
    """

    def post(self, request, pk):
        # Temporalmente se conserva el permiso funcional existente. Separar
        # `reschedule_workorder` será una migración independiente para no
        # mezclar permisos con esta corrección de flujo.
        if not request.user.has_perm("work_orders.assign_workorder"):
            return JsonResponse(
                {
                    "ok": False,
                    "message": "No tiene permiso para reprogramar órdenes de trabajo.",
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

        if not isinstance(payload, dict) or any(
            not isinstance(payload.get(field, ""), str)
            for field in ("date", "reason")
        ):
            return JsonResponse(
                {
                    "ok": False,
                    "message": "Solicitud inválida: fecha y motivo deben ser texto.",
                },
                status=400,
            )

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
                # Se resuelve a través del módulo histórico para conservar el
                # mismo punto de parcheo de las regresiones de concurrencia.
                # En producción sigue siendo django.shortcuts.get_object_or_404.
                order = legacy_views.get_object_or_404(
                    WorkOrder.objects.select_for_update(of=("self",)),
                    pk=pk,
                )
                new_schedule = self._schedule_for(
                    order,
                    form.cleaned_data["date"],
                )

                if order.status == WorkOrder.Status.PENDING:
                    reprogramming = self._schedule_pending(
                        order,
                        new_schedule,
                        request.user,
                        form.cleaned_data["reason"],
                    )
                else:
                    reprogramming = order.reprogram(
                        new_schedule=new_schedule,
                        user=request.user,
                        reason=form.cleaned_data["reason"],
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
        local_schedule = timezone.localtime(order.scheduled_at)

        return JsonResponse(
            {
                "ok": True,
                "order_number": order.order_number,
                "status": order.status,
                "status_display": order.get_status_display(),
                "scheduled_at": local_schedule.isoformat(),
                "date": local_schedule.date().isoformat(),
                "reprogramming_id": reprogramming.pk,
                "stats": _schedule_stats(
                    _open_orders_for_schedule(request),
                    _schedule_week(request),
                    timezone.localdate(),
                ),
                "message": (
                    f"Orden {order.order_number} programada para el "
                    f"{formats.date_format(local_schedule, 'j N')}."
                ),
            }
        )

    @staticmethod
    def _schedule_pending(order, new_schedule, user, reason):
        """Cambia agenda de una PENDING y conserva su estado operativo."""
        previous_schedule = order.scheduled_at

        if previous_schedule and new_schedule == previous_schedule:
            raise ValidationError(
                {
                    "scheduled_at": (
                        "La nueva fecha debe ser diferente "
                        "a la fecha programada actual."
                    )
                }
            )

        if new_schedule <= timezone.now():
            raise ValidationError(
                {
                    "scheduled_at": (
                        "La nueva fecha de atención debe ser futura."
                    )
                }
            )

        now = timezone.now()
        updated = WorkOrder.objects.filter(
            pk=order.pk,
            status=WorkOrder.Status.PENDING,
            scheduled_at=previous_schedule,
        ).update(
            scheduled_at=new_schedule,
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

        order.scheduled_at = new_schedule
        order.updated_at = now

        return WorkOrderReprogramming.objects.create(
            work_order=order,
            previous_schedule=previous_schedule,
            new_schedule=new_schedule,
            reason=reason,
            created_by=user,
        )

    @staticmethod
    def _schedule_for(order, new_date):
        """Combina el nuevo día con la hora ya comprometida, si existe.

        El tablero semanal todavía trabaja con DateTimeField. Si la OT no
        tenía fecha se conserva el comportamiento actual de las 09:00. El
        caso «día acordado, sin hora» se modelará aparte para no inventar que
        las 09:00 sean una promesa al cliente.
        """
        if order.scheduled_at is not None:
            time_of_day = timezone.localtime(order.scheduled_at).time()
        else:
            time_of_day = time(9, 0)

        naive = datetime.combine(new_date, time_of_day)
        return timezone.make_aware(naive, timezone.get_current_timezone())
