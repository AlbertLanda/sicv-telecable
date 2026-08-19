from django import forms

from .models import (
    OrderReason,
    OrderSubtype,
    OrderType,
    WorkOrder,
)
from apps.services.models import Subscription
from apps.organization.models import Branch, Zone


class WorkOrderCreateForm(forms.ModelForm):

    class Meta:
        model = WorkOrder

        fields = [
            "subscription",
            "order_type",
            "subtype",
            "reason",
            "branch",
            "zone",
            "attention_type",
            "priority",
            "detail",
        ]

        widgets = {
            "subscription": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "order_type": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "subtype": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "reason": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "branch": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "zone": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "attention_type": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "priority": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "detail": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": (
                        "Detalle de la solicitud..."
                    ),
                }
            ),
        }

        labels = {
            "subscription": "Suscripción",
            "order_type": "Tipo de orden",
            "subtype": "Subtipo",
            "reason": "Motivo",
            "branch": "Sede",
            "zone": "Zona",
            "attention_type": "Tipo de atención",
            "priority": "Prioridad",
            "detail": "Detalle de la solicitud",
        }

    def __init__(self, *args, **kwargs):
        customer = kwargs.pop("customer", None)

        super().__init__(*args, **kwargs)

        self.customer = customer

        # ---------------------------------------------------------
        # SEDES
        # ---------------------------------------------------------

        self.fields["branch"].queryset = (
            Branch.objects
            .filter(is_active=True)
            .order_by("name")
        )

        # ---------------------------------------------------------
        # ZONAS
        # ---------------------------------------------------------

        self.fields["zone"].queryset = (
            Zone.objects
            .filter(is_active=True)
            .select_related("branch")
            .order_by(
                "branch__name",
                "name",
            )
        )

        # ---------------------------------------------------------
        # SUSCRIPCIONES DEL CLIENTE
        # ---------------------------------------------------------

        self.fields["subscription"].queryset = (
            Subscription.objects.none()
        )

        if customer is not None:
            self.fields["subscription"].queryset = (
                Subscription.objects
                .filter(
                    customer=customer,
                    is_active=True,
                )
                .select_related(
                    "customer",
                    "service_type",
                    "plan",
                    "address",
                )
                .order_by(
                    "service_type__name",
                    "service_number",
                )
            )

        # ---------------------------------------------------------
        # TIPOS DE ORDEN
        # ---------------------------------------------------------

        self.fields["order_type"].queryset = (
            OrderType.objects
            .filter(is_active=True)
            .order_by("name")
        )

        # ---------------------------------------------------------
        # SUBTIPOS
        # ---------------------------------------------------------

        self.fields["subtype"].queryset = (
            OrderSubtype.objects
            .filter(is_active=True)
            .select_related("order_type")
            .order_by(
                "order_type__name",
                "name",
            )
        )

        # ---------------------------------------------------------
        # MOTIVOS
        # ---------------------------------------------------------

        self.fields["reason"].queryset = (
            OrderReason.objects
            .filter(is_active=True)
            .select_related("order_type")
            .order_by(
                "order_type__name",
                "name",
            )
        )

    # -------------------------------------------------------------
    # NÚMERO DE ORDEN
    # -------------------------------------------------------------

    def generate_order_number(self):
        last_order = (
            WorkOrder.objects
            .order_by("-id")
            .first()
        )

        if last_order is None:
            next_number = 1
        else:
            next_number = last_order.id + 1

        return f"OT-{next_number:06d}"

    # -------------------------------------------------------------
    # VALIDACIONES
    # -------------------------------------------------------------

    def clean(self):
        cleaned_data = super().clean()

        subscription = cleaned_data.get("subscription")
        order_type = cleaned_data.get("order_type")
        subtype = cleaned_data.get("subtype")
        reason = cleaned_data.get("reason")

        # ---------------------------------------------------------
        # VALIDAR SUSCRIPCIÓN
        # ---------------------------------------------------------

        if self.customer and subscription:

            if subscription.customer_id != self.customer.pk:
                self.add_error(
                    "subscription",
                    (
                        "La suscripción seleccionada no pertenece "
                        "al cliente."
                    ),
                )

        # ---------------------------------------------------------
        # VALIDAR SUBTIPO
        # ---------------------------------------------------------

        if order_type and subtype:

            if subtype.order_type_id != order_type.pk:
                self.add_error(
                    "subtype",
                    (
                        "El subtipo seleccionado no pertenece "
                        "al tipo de orden."
                    ),
                )

        # ---------------------------------------------------------
        # VALIDAR MOTIVO
        # ---------------------------------------------------------

        if order_type and reason:

            if reason.order_type_id != order_type.pk:
                self.add_error(
                    "reason",
                    (
                        "El motivo seleccionado no pertenece "
                        "al tipo de orden."
                    ),
                )

        return cleaned_data