import uuid

from django import forms
from django.db.models import Q

from apps.services.models import Subscription
from apps.work_orders.models import WorkOrder

from .models import Equipment, EquipmentAssignment


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not field.widget.is_hidden:
                field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"


class EquipmentCreateForm(StyledForm):
    kind = forms.ChoiceField(label="Tipo de equipo", choices=Equipment.Kind.choices)
    brand = forms.CharField(label="Marca", max_length=80)
    model = forms.CharField(label="Modelo", max_length=100)
    serial_number = forms.CharField(label="Número de serie", max_length=100, required=False)
    mac_address = forms.CharField(label="Dirección MAC", max_length=30, required=False, help_text="Ejemplo: AA:BB:CC:DD:EE:FF. Indica al menos serie o MAC.")


class AssignmentForm(StyledForm):
    equipment = forms.ModelChoiceField(label="Equipo disponible", queryset=Equipment.objects.none())
    subscription = forms.ModelChoiceField(label="Servicio del abonado", queryset=Subscription.objects.none())
    work_order = forms.ModelChoiceField(label="Orden de trabajo de referencia", queryset=WorkOrder.objects.none(), required=False)
    notes = forms.CharField(label="Observación", max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    operation_id = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, customer, branch, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment"].queryset = Equipment.objects.filter(branch=branch, status=Equipment.Status.AVAILABLE)
        self.fields["subscription"].queryset = (
            customer.subscriptions.filter(is_active=True).exclude(status=Subscription.Status.CANCELLED)
            .select_related("customer", "service_type", "plan")
        )
        self.fields["work_order"].queryset = WorkOrder.objects.filter(subscription__customer=customer).select_related("order_type").order_by("-pk")
        self.fields["subscription"].label_from_instance = lambda item: f"{item.service_code} · {item.plan.name}"
        self.fields["work_order"].label_from_instance = lambda item: f"{item.order_number} · {item.order_type.name}"
        # Permite validar el mismo envío aunque su equipo ya esté asignado.
        # El servicio compara todos los datos y nunca reactiva una retirada.
        if self.is_bound:
            try:
                token = uuid.UUID(str(self.data.get("operation_id", "")))
            except ValueError:
                return
            previous = EquipmentAssignment.objects.filter(
                operation_id=token, assigned_by=user,
                subscription__customer=customer, equipment__branch=branch,
            ).first()
            if previous:
                self.fields["equipment"].queryset = Equipment.objects.filter(branch=branch).filter(
                    Q(status=Equipment.Status.AVAILABLE) | Q(pk=previous.equipment_id)
                )
                self.fields["subscription"].queryset = customer.subscriptions.filter(pk=previous.subscription_id)


class RemovalForm(StyledForm):
    reason = forms.CharField(label="Motivo del retiro", min_length=5, max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
    return_status = forms.ChoiceField(
        label="Estado después del retiro",
        choices=[choice for choice in Equipment.Status.choices if choice[0] != Equipment.Status.ASSIGNED],
        initial=Equipment.Status.REVIEW,
    )


class EquipmentFilterForm(StyledForm):
    q = forms.CharField(label="Buscar serie, MAC, marca o modelo", required=False, max_length=100)
    status = forms.ChoiceField(label="Estado", required=False, choices=[("", "Todos los estados")] + list(Equipment.Status.choices))


class ReviewForm(RemovalForm):
    reason = forms.CharField(label="Resultado de la revisión", min_length=5, max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
    operation_id = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["return_status"].label = "Nuevo estado del equipo"
