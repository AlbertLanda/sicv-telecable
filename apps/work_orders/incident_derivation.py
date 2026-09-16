"""Derivación de una incidencia NOC hacia una avería física de campo.

La incidencia y la avería son órdenes distintas. La primera conserva todo el
trabajo remoto realizado por NOC y termina en DERIVED; la segunda nace PENDING,
FIELD y sin técnico para entrar al pool compartido del canal técnico.

La creación de la avería y el cambio de estado de la incidencia ocurren en la
misma transacción: nunca queda una avería huérfana si la derivación falla.
"""

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import FormView

from apps.work_orders.field_order_types import FAULT_ORDER_TYPE_CODES
from apps.work_orders.incident_noc import (
    INCIDENT_TAKE_PERMISSION,
    _lock_incident,
    _require_current_handler,
    _require_permission,
    incident_current_handler,
)
from apps.work_orders.models import (
    OrderReason,
    OrderType,
    WorkOrder,
    WorkOrderFieldSheet,
    WorkOrderStatusHistory,
)
from apps.work_orders.services import (
    create_work_order,
    get_subscription_technical_context,
)


DERIVATION_MARKER = "Incidencia NOC origen: {order_number}"


class IncidentDeriveFaultForm(forms.Form):
    """Solo pide a NOC la decisión técnica necesaria para derivar a campo."""

    fault_type = forms.ModelChoiceField(
        queryset=OrderType.objects.none(),
        label="Tipo de avería",
        empty_label="Seleccione la avería de campo...",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    fault_reason = forms.ModelChoiceField(
        queryset=OrderReason.objects.none(),
        label="Motivo de avería",
        required=False,
        empty_label="Sin motivo catalogado",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    diagnosis = forms.CharField(
        label="Diagnóstico NOC",
        min_length=5,
        max_length=3000,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": (
                    "Ej.: Potencia óptica fuera de rango; las pruebas remotas "
                    "indican que se requiere revisión física."
                ),
            }
        ),
    )
    field_detail = forms.CharField(
        label="Detalle para el técnico de campo",
        min_length=5,
        max_length=3000,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": (
                    "Indique qué debe revisar el técnico y cualquier contexto "
                    "que evite repetir el diagnóstico remoto."
                ),
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        subscription = kwargs.pop("subscription", None)
        super().__init__(*args, **kwargs)
        self.subscription = subscription

        if subscription is None:
            fault_types = OrderType.objects.none()
        else:
            fault_types = (
                OrderType.objects
                .filter(code__in=FAULT_ORDER_TYPE_CODES, is_active=True)
                .for_service_type(subscription.service_type_id)
                .order_by("name")
            )

        self.fields["fault_type"].queryset = fault_types

        # Si la suscripción solo admite un tipo de avería (p. ej. solo
        # Internet), se deja preseleccionado para ahorrar un clic sin volver
        # el valor inmutable.
        if not self.is_bound and fault_types.count() == 1:
            self.fields["fault_type"].initial = fault_types.first()

        reasons = OrderReason.objects.filter(
            order_type__in=fault_types,
            is_active=True,
        ).select_related("order_type")

        selected_type_id = None
        if self.is_bound:
            selected_type_id = self.data.get("fault_type")
        elif self.fields["fault_type"].initial:
            selected_type_id = self.fields["fault_type"].initial.pk

        if selected_type_id:
            reasons = reasons.filter(order_type_id=selected_type_id)

        self.fields["fault_reason"].queryset = reasons.order_by(
            "order_type__name", "name"
        )

    def clean(self):
        cleaned = super().clean()
        fault_type = cleaned.get("fault_type")
        fault_reason = cleaned.get("fault_reason")

        if fault_type and fault_type.code not in FAULT_ORDER_TYPE_CODES:
            self.add_error("fault_type", "El tipo seleccionado no corresponde a una avería de campo.")

        if (
            fault_type
            and self.subscription
            and not fault_type.applies_to_service_type(self.subscription.service_type_id)
        ):
            self.add_error(
                "fault_type",
                "La avería seleccionada no corresponde al servicio de esta suscripción.",
            )

        if fault_reason and fault_type and fault_reason.order_type_id != fault_type.pk:
            self.add_error(
                "fault_reason",
                "El motivo seleccionado no pertenece al tipo de avería indicado.",
            )

        return cleaned


def derivation_marker(order):
    return DERIVATION_MARKER.format(order_number=order.order_number)


def derived_fault_for_incident(order):
    """Localiza la avería generada por esta incidencia, si ya existe.

    La relación se conserva en el texto inmutable de creación de la avería y
    en el historial del padre. Esta primera versión evita introducir un nuevo
    FK únicamente para el puente NOC->campo; cuando el módulo completo de
    averías se consolide se podrá normalizar esa relación mediante migración.
    """
    if order is None or order.pk is None:
        return None

    return (
        WorkOrder.objects
        .filter(
            subscription_id=order.subscription_id,
            order_type__code__in=FAULT_ORDER_TYPE_CODES,
            detail__startswith=derivation_marker(order),
        )
        .select_related("order_type", "reason", "created_by")
        .order_by("created_at", "pk")
        .first()
    )


def _seed_fault_field_sheet_from_previous_context(fault_order):
    """Carga en la nueva avería los últimos datos técnicos conocidos.

    NAP, borne, MAC/equipo y precinto describen el estado conocido del punto de
    servicio. Si ya fueron registrados en una OT física anterior no se obliga
    al siguiente técnico a digitarlos de nuevo: la avería nace con una copia
    editable de esos valores. Las observaciones NO se heredan porque pertenecen
    a la visita anterior y deben quedar vacías para la nueva atención.

    La OT anterior conserva su propia ficha sin modificación; esta es una
    fotografía inicial independiente que el técnico de la avería podrá
    corregir cuando tome la orden.
    """
    context = get_subscription_technical_context(
        fault_order.subscription,
        exclude_order=fault_order,
    )

    if not context or context.get("field_sheet") is None:
        return None

    source_sheet = context["field_sheet"]

    if source_sheet.is_empty:
        return None

    inherited_values = {
        "nap": source_sheet.nap,
        "terminal": source_sheet.terminal,
        "equipment_code": source_sheet.equipment_code,
        "seal_number": source_sheet.seal_number,
    }

    if not any(inherited_values.values()):
        return None

    return WorkOrderFieldSheet.objects.create(
        work_order=fault_order,
        notes="",
        updated_by=None,
        **inherited_values,
    )


def _mark_incident_derived(order, user, fault_order, diagnosis):
    """IN_PROGRESS -> DERIVED con defensa optimista y trazabilidad."""
    now = timezone.now()
    updated = WorkOrder.objects.filter(
        pk=order.pk,
        order_type__code="INCIDENT",
        status=WorkOrder.Status.IN_PROGRESS,
    ).update(
        status=WorkOrder.Status.DERIVED,
        updated_at=now,
    )

    if not updated:
        raise ValidationError(
            "La incidencia cambió mientras se generaba la avería. "
            "Actualice la ficha antes de volver a intentarlo."
        )

    order.status = WorkOrder.Status.DERIVED
    order.updated_at = now

    WorkOrderStatusHistory.objects.create(
        work_order=order,
        previous_status=WorkOrder.Status.IN_PROGRESS,
        new_status=WorkOrder.Status.DERIVED,
        changed_by=user,
        remarks=(
            f"Incidencia derivada a campo como {fault_order.order_number} "
            f"({fault_order.order_type.name}). Diagnóstico NOC: {diagnosis}"
        ),
    )

    return order


@transaction.atomic
def derive_incident_to_fault(
    order,
    user,
    *,
    fault_type,
    diagnosis,
    field_detail,
    fault_reason=None,
):
    """Crea una avería física y deja la incidencia marcada como derivada."""
    _require_permission(user, INCIDENT_TAKE_PERMISSION, "deriva la incidencia a campo")
    order = _lock_incident(order)
    _require_current_handler(order, user, "derivarse a campo")

    diagnosis = (diagnosis or "").strip()
    field_detail = (field_detail or "").strip()

    if len(diagnosis) < 5:
        raise ValidationError("Debe registrar el diagnóstico NOC antes de derivar.")
    if len(field_detail) < 5:
        raise ValidationError("Debe indicar el detalle que recibirá el técnico de campo.")

    if fault_type is None or fault_type.pk is None:
        raise ValidationError("Debe seleccionar un tipo de avería registrado.")
    if not fault_type.is_active or fault_type.code not in FAULT_ORDER_TYPE_CODES:
        raise ValidationError("El tipo seleccionado no corresponde a una avería activa.")
    if not fault_type.applies_to_service_type(order.subscription.service_type_id):
        raise ValidationError("La avería seleccionada no corresponde al servicio de la incidencia.")

    if fault_reason is not None:
        if not fault_reason.is_active or fault_reason.order_type_id != fault_type.pk:
            raise ValidationError("El motivo seleccionado no pertenece a la avería indicada.")

    # Bloqueo defensivo adicional. Normalmente el estado DERIVED ya impide
    # una segunda derivación, pero esta consulta también detecta una relación
    # previa si una operación histórica quedó con estado irregular.
    existing = derived_fault_for_incident(order)
    if existing is not None:
        raise ValidationError(
            f"Esta incidencia ya fue derivada a la avería {existing.order_number}."
        )

    marker = derivation_marker(order)
    child_detail = (
        f"{marker}\n\n"
        f"Reporte original: {order.reason_text}\n\n"
        f"Diagnóstico NOC: {diagnosis}\n\n"
        f"Detalle para campo: {field_detail}"
    )

    fault_order = create_work_order(
        subscription=order.subscription,
        order_type=fault_type,
        created_by=user,
        customer=order.subscription.customer,
        branch=order.branch,
        zone=order.zone,
        reason=fault_reason,
        reason_text=order.reason_text,
        attention_type=WorkOrder.AttentionType.FIELD,
        priority=WorkOrder.Priority.NORMAL,
        detail=child_detail,
        scheduled_at=None,
    )

    _seed_fault_field_sheet_from_previous_context(fault_order)

    _mark_incident_derived(
        order,
        user=user,
        fault_order=fault_order,
        diagnosis=diagnosis,
    )

    return order, fault_order


class IncidentDeriveFaultView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    permission_required = INCIDENT_TAKE_PERMISSION
    raise_exception = True
    form_class = IncidentDeriveFaultForm
    template_name = "work_orders/incident_noc_derive_fault.html"

    def get_work_order(self):
        if not hasattr(self, "_work_order"):
            self._work_order = get_object_or_404(
                WorkOrder.objects.select_related(
                    "order_type",
                    "subscription",
                    "subscription__customer",
                    "subscription__service_type",
                    "subscription__plan",
                    "subscription__address",
                    "branch",
                    "zone",
                ),
                pk=self.kwargs["pk"],
                order_type__code="INCIDENT",
            )
        return self._work_order

    def _is_current_handler(self, order):
        handler = incident_current_handler(order)
        return bool(
            order.status == WorkOrder.Status.IN_PROGRESS
            and handler is not None
            and handler.pk == self.request.user.pk
        )

    def get(self, request, *args, **kwargs):
        order = self.get_work_order()
        if not self._is_current_handler(order):
            messages.error(
                request,
                "Solo el responsable NOC actual puede derivar esta incidencia a campo.",
            )
            return redirect("work_orders:incident_noc_detail", pk=order.pk)
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["subscription"] = self.get_work_order().subscription
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.get_work_order()
        context["order"] = order
        context["customer"] = order.subscription.customer
        return context

    def form_valid(self, form):
        order = self.get_work_order()
        try:
            order, fault_order = derive_incident_to_fault(
                order,
                self.request.user,
                fault_type=form.cleaned_data["fault_type"],
                fault_reason=form.cleaned_data.get("fault_reason"),
                diagnosis=form.cleaned_data["diagnosis"],
                field_detail=form.cleaned_data["field_detail"],
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages)
            return self.form_invalid(form)

        messages.success(
            self.request,
            (
                f"Incidencia {order.order_number} derivada correctamente. "
                f"Se generó la avería {fault_order.order_number} para el canal técnico."
            ),
        )

        url = reverse("work_orders:incident_noc_detail", kwargs={"pk": order.pk})
        if self.request.GET.get("origin") == "customer_orders":
            url += "?origin=customer_orders"
        return redirect(url)
