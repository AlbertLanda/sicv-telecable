"""Flujo operativo de incidencias atendidas por NOC.

Este módulo extiende la primera versión de incidencias sin mezclarla con el
flujo de campo. Una incidencia puede ser tomada por un solo operador, liberada
al terminar un turno, reprogramada para un nuevo contacto y retomada por otro
NOC. La trazabilidad se apoya en WorkOrderStatusHistory y
WorkOrderReprogramming, de modo que no se sobrescribe el trabajo anterior.
"""

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.work_orders.forms import IncidentCloseForm
from apps.work_orders.models import (
    WorkOrder,
    WorkOrderParticipation,
    WorkOrderReprogramming,
    WorkOrderStatusHistory,
)
from apps.work_orders.services import (
    close_incident_attention,
    close_work_order_participation,
    get_subscription_technical_context,
    open_work_order_participation,
)


INCIDENT_VIEW_PERMISSION = "work_orders.view_incident"
INCIDENT_TAKE_PERMISSION = "work_orders.start_incident"
INCIDENT_CLOSE_PERMISSION = "work_orders.close_incident"
INCIDENT_CANCEL_PERMISSION = "work_orders.cancel_workorder"


class IncidentReleaseForm(forms.Form):
    reason = forms.CharField(
        label="Motivo de liberación",
        required=True,
        min_length=5,
        max_length=1000,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": (
                    "Ej.: Fin de turno. La incidencia queda disponible "
                    "para que otro operador NOC continúe la atención."
                ),
            }
        ),
    )


class IncidentRescheduleForm(forms.Form):
    scheduled_for = forms.DateTimeField(
        label="Próximo contacto",
        required=True,
        input_formats=[
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
        ],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "class": "form-control",
                "type": "datetime-local",
            },
        ),
    )

    reason = forms.CharField(
        label="Motivo",
        required=True,
        min_length=5,
        max_length=1000,
        strip=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ej.: Cliente solicita llamada mañana a las 10:00.",
            }
        ),
    )

    notes = forms.CharField(
        label="Observación",
        required=False,
        max_length=3000,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": (
                    "Contexto que debe conocer el siguiente operador NOC "
                    "antes de retomar el contacto."
                ),
            }
        ),
    )


class IncidentCancelForm(forms.Form):
    reason = forms.CharField(
        label="Motivo de anulación",
        required=True,
        min_length=5,
        max_length=1000,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Explique por qué la incidencia ya no debe continuar...",
            }
        ),
    )


def _require_permission(user, permission, action):
    if user is None or user.pk is None:
        raise ValidationError(f"Debe indicar el usuario que {action}.")

    if not user.is_active:
        raise ValidationError(f"El usuario que {action} debe estar activo.")

    if not user.has_perm(permission):
        raise ValidationError(
            f"El usuario no está autorizado para {action}. "
            f"Requiere el permiso {permission}."
        )


def _lock_incident(order):
    """Relee y bloquea la incidencia antes de cualquier cambio operativo."""
    if order is None or order.pk is None:
        raise ValidationError("Debe indicar una incidencia registrada.")

    try:
        locked = (
            WorkOrder.objects
            .select_for_update()
            .select_related(
                "order_type",
                "subscription",
                "subscription__customer",
                "subscription__service_type",
                "subscription__plan",
            )
            .get(pk=order.pk)
        )
    except WorkOrder.DoesNotExist:
        raise ValidationError("La incidencia indicada ya no existe.")

    if not locked.is_incident:
        raise ValidationError("La orden indicada no es una incidencia NOC.")

    return locked


def incident_current_handler(order):
    """Operador que posee la incidencia mientras está EN ATENCIÓN.

    No se agrega un segundo campo de asignación: la transición que lleva a
    IN_PROGRESS ya registra `changed_by`. La última de esas transiciones es la
    toma vigente y las anteriores permanecen como historial de responsables.
    """
    if order.status != WorkOrder.Status.IN_PROGRESS:
        return None

    history = getattr(order, "_noc_status_history", None)

    if history is not None:
        candidates = [
            entry
            for entry in history
            if entry.new_status == WorkOrder.Status.IN_PROGRESS
        ]
        if not candidates:
            return None
        entry = max(candidates, key=lambda value: (value.changed_at, value.pk))
        return entry.changed_by

    entry = (
        order.status_history
        .filter(new_status=WorkOrder.Status.IN_PROGRESS)
        .select_related("changed_by")
        .order_by("-changed_at", "-pk")
        .first()
    )

    return entry.changed_by if entry else None


def _require_current_handler(order, user, action):
    if order.status != WorkOrder.Status.IN_PROGRESS:
        raise ValidationError(
            f"Solo una incidencia en atención puede {action}. "
            f"Estado actual: {order.get_status_display()}."
        )

    handler = incident_current_handler(order)

    if handler is None:
        raise ValidationError(
            "La incidencia está en atención pero no tiene un responsable NOC "
            "identificable. Libérela o regularice su historial antes de continuar."
        )

    if handler.pk != user.pk:
        raise ValidationError(
            f"La incidencia está siendo atendida por {handler}. "
            "Solo el responsable actual puede modificar su atención."
        )

    return handler


def _extended_incident_transition(order, new_status, user, remarks=""):
    """Transiciones adicionales del trabajo colaborativo NOC.

    WorkOrder.change_status() cubre el flujo original PENDING -> IN_PROGRESS
    -> ATTENDED. Estas transiciones representan necesidades posteriores del
    NOC (liberar, reprogramar, retomar y anular una incidencia ya tomada).
    Se mantiene la misma defensa de concurrencia: el UPDATE exige que el
    estado en base de datos siga siendo el que el operador leyó.
    """
    allowed = {
        (WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.PENDING),
        (WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.REPROGRAMMED),
        (WorkOrder.Status.REPROGRAMMED, WorkOrder.Status.IN_PROGRESS),
        (WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.CANCELLED),
        (WorkOrder.Status.REPROGRAMMED, WorkOrder.Status.CANCELLED),
    }

    previous_status = order.status

    if (previous_status, new_status) not in allowed:
        raise ValidationError(
            "La transición solicitada no pertenece al flujo operativo NOC: "
            f"{order.get_status_display()} -> {WorkOrder.Status(new_status).label}."
        )

    now = timezone.now()
    updated = WorkOrder.objects.filter(
        pk=order.pk,
        order_type__code="INCIDENT",
        status=previous_status,
    ).update(
        status=new_status,
        updated_at=now,
    )

    if not updated:
        raise ValidationError(
            "La incidencia cambió mientras se procesaba la solicitud. "
            "Actualice la ficha antes de volver a intentarlo."
        )

    order.status = new_status
    order.updated_at = now

    WorkOrderStatusHistory.objects.create(
        work_order=order,
        previous_status=previous_status,
        new_status=new_status,
        changed_by=user,
        remarks=(remarks or "").strip(),
    )

    return order


@transaction.atomic
def take_incident(order, user, remarks=""):
    """Toma exclusiva: PENDING -> IN_PROGRESS.

    La fila queda bloqueada hasta confirmar la transacción. Si dos NOC pulsan
    al mismo tiempo, el segundo relee el estado ya modificado y recibe un
    rechazo en lugar de trabajar la misma incidencia.
    """
    _require_permission(user, INCIDENT_TAKE_PERMISSION, "toma la incidencia")
    order = _lock_incident(order)

    if order.status != WorkOrder.Status.PENDING:
        handler = incident_current_handler(order)
        detail = f" por {handler}" if handler else ""
        raise ValidationError(
            "Esta incidencia ya no está disponible para tomarla"
            f"{detail}. Estado actual: {order.get_status_display()}."
        )

    if order.started_at is None:
        order.started_at = timezone.now()
        order.save(update_fields=["started_at", "updated_at"])

    order.change_status(
        WorkOrder.Status.IN_PROGRESS,
        user=user,
        remarks=(remarks or "Incidencia tomada por NOC.").strip(),
    )
    open_work_order_participation(
        order,
        user,
        source=WorkOrderParticipation.Source.NOC,
        remarks="Incidencia tomada por NOC.",
        recorded_by=user,
    )

    return order


@transaction.atomic
def release_incident(order, user, reason):
    """Devuelve una incidencia en atención al pool NOC: IN_PROGRESS -> PENDING."""
    _require_permission(user, INCIDENT_TAKE_PERMISSION, "libera la incidencia")
    order = _lock_incident(order)
    _require_current_handler(order, user, "liberarse")

    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValidationError("Debe indicar el motivo de liberación con al menos 5 caracteres.")

    order = _extended_incident_transition(
        order,
        WorkOrder.Status.PENDING,
        user,
        remarks=f"Incidencia liberada por NOC. Motivo: {reason}",
    )
    close_work_order_participation(
        order,
        user,
        source=WorkOrderParticipation.Source.NOC,
    )
    return order


@transaction.atomic
def reschedule_incident(order, user, scheduled_for, reason, notes=""):
    """Programa un nuevo contacto y conserva la reprogramación como historial."""
    _require_permission(user, INCIDENT_TAKE_PERMISSION, "reprograma la incidencia")
    order = _lock_incident(order)
    _require_current_handler(order, user, "reprogramarse")

    reason = (reason or "").strip()
    notes = (notes or "").strip()

    if len(reason) < 5:
        raise ValidationError("Debe indicar el motivo de la reprogramación.")

    if scheduled_for is None or scheduled_for <= timezone.now():
        raise ValidationError("El próximo contacto debe programarse para una fecha futura.")

    reprogramming = WorkOrderReprogramming.objects.create(
        work_order=order,
        previous_schedule=None,
        previous_schedule_date=None,
        new_schedule=scheduled_for,
        new_schedule_date=None,
        reason=reason,
        created_by=user,
    )

    remarks = f"Contacto NOC reprogramado para {timezone.localtime(scheduled_for):%d/%m/%Y %H:%M}. Motivo: {reason}"
    if notes:
        remarks += f" Observación: {notes}"

    _extended_incident_transition(
        order,
        WorkOrder.Status.REPROGRAMMED,
        user,
        remarks=remarks,
    )
    close_work_order_participation(
        order,
        user,
        source=WorkOrderParticipation.Source.NOC,
    )

    return order, reprogramming


@transaction.atomic
def resume_incident(order, user, remarks=""):
    """Retoma una incidencia reprogramada; cualquier NOC autorizado puede hacerlo."""
    _require_permission(user, INCIDENT_TAKE_PERMISSION, "retoma la incidencia")
    order = _lock_incident(order)

    if order.status != WorkOrder.Status.REPROGRAMMED:
        raise ValidationError(
            "Solo una incidencia reprogramada puede retomarse. "
            f"Estado actual: {order.get_status_display()}."
        )

    order = _extended_incident_transition(
        order,
        WorkOrder.Status.IN_PROGRESS,
        user,
        remarks=(remarks or "Contacto reprogramado retomado por NOC.").strip(),
    )
    open_work_order_participation(
        order,
        user,
        source=WorkOrderParticipation.Source.NOC,
        remarks="Incidencia retomada por NOC.",
        recorded_by=user,
    )
    return order


@transaction.atomic
def close_owned_incident(order, user, attention_detail, observations="", remarks=""):
    """Cierra únicamente si el ejecutor es el NOC que posee la incidencia."""
    _require_permission(user, INCIDENT_CLOSE_PERMISSION, "finaliza la incidencia")
    order = _lock_incident(order)
    _require_current_handler(order, user, "finalizarse")

    order = close_incident_attention(
        order,
        user=user,
        attention_detail=attention_detail,
        observations=observations,
        remarks=remarks,
    )
    close_work_order_participation(
        order,
        user,
        source=WorkOrderParticipation.Source.NOC,
    )
    return order


@transaction.atomic
def cancel_incident(order, user, reason):
    """Anulación administrativa desde cualquier estado operativo de NOC."""
    _require_permission(user, INCIDENT_CANCEL_PERMISSION, "anula la incidencia")
    order = _lock_incident(order)

    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValidationError("Debe indicar el motivo de la anulación con al menos 5 caracteres.")

    if order.status == WorkOrder.Status.PENDING:
        order.cancel(user=user, reason=reason)
        return order

    if order.status in (
        WorkOrder.Status.IN_PROGRESS,
        WorkOrder.Status.REPROGRAMMED,
    ):
        previous_status = order.status
        order = _extended_incident_transition(
            order,
            WorkOrder.Status.CANCELLED,
            user,
            remarks=reason,
        )
        if previous_status == WorkOrder.Status.IN_PROGRESS:
            close_work_order_participation(
                order,
                user,
                source=WorkOrderParticipation.Source.NOC,
            )
        return order

    raise ValidationError(
        "No se puede anular una incidencia en estado "
        f"{order.get_status_display()}."
    )


def latest_incident_follow_up(order):
    if order.status != WorkOrder.Status.REPROGRAMMED:
        return None

    return (
        order.reprogrammings
        .select_related("created_by")
        .order_by("-created_at", "-pk")
        .first()
    )


def prior_incidents(order, limit=10):
    """Incidencias anteriores de la misma suscripción para diagnóstico NOC."""
    return list(
        WorkOrder.objects
        .filter(
            subscription=order.subscription,
            order_type__code="INCIDENT",
        )
        .exclude(pk=order.pk)
        .select_related(
            "incident_detail",
            "incident_detail__attended_by",
            "created_by",
        )
        .order_by("-created_at", "-pk")[:limit]
    )


def _incident_queryset():
    return (
        WorkOrder.objects
        .filter(order_type__code="INCIDENT")
        .select_related(
            "subscription",
            "subscription__customer",
            "subscription__service_type",
            "subscription__plan",
            "branch",
            "created_by",
        )
        .prefetch_related(
            "status_history__changed_by",
            "reprogrammings__created_by",
        )
    )


def _prepare_queue_item(order):
    # Evita una consulta por tarjeta al resolver el responsable vigente.
    order._noc_status_history = list(order.status_history.all())
    handler = incident_current_handler(order)

    follow_up = None
    if order.status == WorkOrder.Status.REPROGRAMMED:
        follow_up = max(
            list(order.reprogrammings.all()),
            key=lambda value: (value.created_at, value.pk),
            default=None,
        )

    return {
        "order": order,
        "handler": handler,
        "follow_up": follow_up,
        "is_overdue": bool(
            follow_up
            and follow_up.new_schedule
            and follow_up.new_schedule <= timezone.now()
        ),
    }


class NocIncidentQueueView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = INCIDENT_VIEW_PERMISSION
    raise_exception = True
    template_name = "work_orders/incident_noc_queue.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        orders = list(
            _incident_queryset()
            .filter(
                status__in=[
                    WorkOrder.Status.PENDING,
                    WorkOrder.Status.IN_PROGRESS,
                    WorkOrder.Status.REPROGRAMMED,
                ]
            )
            .order_by("created_at", "pk")
        )

        items = [_prepare_queue_item(order) for order in orders]

        context.update({
            "items": items,
            "pending_count": sum(
                item["order"].status == WorkOrder.Status.PENDING
                for item in items
            ),
            "in_progress_count": sum(
                item["order"].status == WorkOrder.Status.IN_PROGRESS
                for item in items
            ),
            "reprogrammed_count": sum(
                item["order"].status == WorkOrder.Status.REPROGRAMMED
                for item in items
            ),
            "overdue_count": sum(item["is_overdue"] for item in items),
            "initial_pending_ids": [
                item["order"].pk
                for item in items
                if item["order"].status == WorkOrder.Status.PENDING
            ],
        })

        return context


class NocIncidentDetailView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = INCIDENT_VIEW_PERMISSION
    raise_exception = True
    template_name = "work_orders/incident_noc_detail.html"

    def get_work_order(self):
        if not hasattr(self, "_work_order"):
            self._work_order = get_object_or_404(
                _incident_queryset(),
                pk=self.kwargs["pk"],
            )
        return self._work_order

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.get_work_order()
        order._noc_status_history = list(order.status_history.all())
        handler = incident_current_handler(order)
        follow_up = latest_incident_follow_up(order)

        context.update({
            "order": order,
            "customer": order.subscription.customer,
            "handler": handler,
            "is_current_handler": bool(
                handler and handler.pk == self.request.user.pk
            ),
            "follow_up": follow_up,
            "reprogrammings": order.reprogrammings.select_related(
                "created_by"
            ).order_by("-created_at", "-pk"),
            "status_history": order.status_history.select_related(
                "changed_by"
            ).order_by("-changed_at", "-pk"),
            "prior_incidents": prior_incidents(order),
            "technical_context": get_subscription_technical_context(
                order.subscription,
                exclude_order=order,
            ),
            "can_cancel": (
                order.status in (
                    WorkOrder.Status.PENDING,
                    WorkOrder.Status.IN_PROGRESS,
                    WorkOrder.Status.REPROGRAMMED,
                )
                and self.request.user.has_perm(INCIDENT_CANCEL_PERMISSION)
            ),
        })

        return context


class IncidentClaimView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = INCIDENT_TAKE_PERMISSION
    raise_exception = True

    def post(self, request, pk):
        order = get_object_or_404(WorkOrder, pk=pk, order_type__code="INCIDENT")
        try:
            order = take_incident(order, request.user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(
                request,
                f"Incidencia {order.order_number} tomada correctamente. Ahora eres el responsable NOC.",
            )
        return redirect("work_orders:incident_noc_detail", pk=order.pk)

    def get(self, request, pk):
        return redirect("work_orders:incident_noc_detail", pk=pk)


class IncidentReleaseView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    permission_required = INCIDENT_TAKE_PERMISSION
    raise_exception = True
    form_class = IncidentReleaseForm
    template_name = "work_orders/incident_noc_release.html"

    def get_work_order(self):
        if not hasattr(self, "_work_order"):
            self._work_order = get_object_or_404(
                _incident_queryset(), pk=self.kwargs["pk"]
            )
        return self._work_order

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["order"] = self.get_work_order()
        return context

    def form_valid(self, form):
        order = self.get_work_order()
        try:
            order = release_incident(
                order,
                self.request.user,
                form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages)
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Incidencia {order.order_number} liberada. Otro operador NOC ya puede tomarla.",
        )
        return redirect("work_orders:incident_noc_queue")


class IncidentRescheduleView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    permission_required = INCIDENT_TAKE_PERMISSION
    raise_exception = True
    form_class = IncidentRescheduleForm
    template_name = "work_orders/incident_noc_reschedule.html"

    def get_work_order(self):
        if not hasattr(self, "_work_order"):
            self._work_order = get_object_or_404(
                _incident_queryset(), pk=self.kwargs["pk"]
            )
        return self._work_order

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["order"] = self.get_work_order()
        return context

    def form_valid(self, form):
        order = self.get_work_order()
        try:
            order, reprogramming = reschedule_incident(
                order,
                self.request.user,
                scheduled_for=form.cleaned_data["scheduled_for"],
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data.get("notes", ""),
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages)
            return self.form_invalid(form)

        local_date = timezone.localtime(reprogramming.new_schedule)
        messages.success(
            self.request,
            f"Incidencia {order.order_number} reprogramada para {local_date:%d/%m/%Y %H:%M}.",
        )
        return redirect("work_orders:incident_noc_detail", pk=order.pk)


class IncidentResumeView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = INCIDENT_TAKE_PERMISSION
    raise_exception = True

    def post(self, request, pk):
        order = get_object_or_404(WorkOrder, pk=pk, order_type__code="INCIDENT")
        try:
            order = resume_incident(order, request.user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(
                request,
                f"Incidencia {order.order_number} retomada. Ahora eres el responsable NOC.",
            )
        return redirect("work_orders:incident_noc_detail", pk=order.pk)

    def get(self, request, pk):
        return redirect("work_orders:incident_noc_detail", pk=pk)


class IncidentNocCloseView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    permission_required = INCIDENT_CLOSE_PERMISSION
    raise_exception = True
    form_class = IncidentCloseForm
    template_name = "work_orders/incident_close.html"

    def get_work_order(self):
        if not hasattr(self, "_work_order"):
            self._work_order = get_object_or_404(
                _incident_queryset(), pk=self.kwargs["pk"]
            )
        return self._work_order

    def get(self, request, *args, **kwargs):
        order = self.get_work_order()
        handler = incident_current_handler(order)
        if (
            order.status != WorkOrder.Status.IN_PROGRESS
            or handler is None
            or handler.pk != request.user.pk
        ):
            messages.error(
                request,
                "Solo el responsable NOC actual puede finalizar esta incidencia.",
            )
            return redirect("work_orders:incident_noc_detail", pk=order.pk)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.get_work_order()
        context["order"] = order
        context["customer"] = order.subscription.customer
        context["technical_context"] = get_subscription_technical_context(
            order.subscription,
            exclude_order=order,
        )
        return context

    def form_valid(self, form):
        order = self.get_work_order()
        try:
            order = close_owned_incident(
                order,
                self.request.user,
                attention_detail=form.cleaned_data["attention_detail"],
                observations=form.cleaned_data.get("observations", ""),
                remarks="Incidencia finalizada por NOC.",
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages)
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Incidencia {order.order_number} atendida correctamente por NOC.",
        )
        return redirect("work_orders:incident_noc_detail", pk=order.pk)


class IncidentNocCancelView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    permission_required = INCIDENT_CANCEL_PERMISSION
    raise_exception = True
    form_class = IncidentCancelForm
    template_name = "work_orders/incident_noc_cancel.html"

    def get_work_order(self):
        if not hasattr(self, "_work_order"):
            self._work_order = get_object_or_404(
                _incident_queryset(), pk=self.kwargs["pk"]
            )
        return self._work_order

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["order"] = self.get_work_order()
        return context

    def form_valid(self, form):
        order = self.get_work_order()
        try:
            order = cancel_incident(
                order,
                self.request.user,
                form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages)
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Incidencia {order.order_number} anulada. El motivo quedó registrado en el historial.",
        )
        return redirect("work_orders:incident_noc_detail", pk=order.pk)


class IncidentNotificationsView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Resumen ligero para el polling de la bandeja NOC."""
    permission_required = INCIDENT_VIEW_PERMISSION
    raise_exception = True

    def get(self, request):
        pending = list(
            _incident_queryset()
            .filter(status=WorkOrder.Status.PENDING)
            .order_by("-created_at", "-pk")[:20]
        )

        due = []
        for order in (
            _incident_queryset()
            .filter(status=WorkOrder.Status.REPROGRAMMED)
            .order_by("created_at", "pk")
        ):
            follow_up = latest_incident_follow_up(order)
            if (
                follow_up
                and follow_up.new_schedule
                and follow_up.new_schedule <= timezone.now()
            ):
                due.append(order)

        return JsonResponse({
            "pending_count": len(pending),
            "due_count": len(due),
            "pending": [
                {
                    "id": order.pk,
                    "number": order.order_number,
                    "customer": str(order.subscription.customer),
                    "reason": order.reason_text,
                    "created_at": order.created_at.isoformat(),
                    "detail_url": reverse(
                        "work_orders:incident_noc_detail",
                        kwargs={"pk": order.pk},
                    ),
                }
                for order in pending
            ],
        })
