from django import forms

from .models import Subscription, ServiceType, Plan
from apps.customers.models import CustomerAddress


class SubscriptionCreateForm(forms.ModelForm):

    class Meta:
        model = Subscription

        fields = [
            "address",
            "service_type",
            "plan",
            "service_number",
            "billing_cycle",
        ]

        widgets = {
            "address": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "service_type": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "plan": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "service_number": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                }
            ),
            "billing_cycle": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                }
            ),
        }

        labels = {
            "address": "Dirección",
            "service_type": "Tipo de servicio",
            "plan": "Plan",
            "service_number": "Número de servicio",
            "billing_cycle": "Ciclo de facturación",
        }

    def __init__(self, *args, **kwargs):
        customer = kwargs.pop("customer", None)

        super().__init__(*args, **kwargs)

        self.customer = customer

        # ---------------------------------------------------------
        # DIRECCIONES DEL CLIENTE
        # ---------------------------------------------------------

        self.fields["address"].queryset = (
            CustomerAddress.objects.none()
        )

        if customer is not None:
            self.fields["address"].queryset = (
                CustomerAddress.objects
                .filter(
                    customer=customer,
                    is_active=True,
                )
                .select_related("zone")
                .order_by(
                    "-is_primary",
                    "address",
                )
            )

        # ---------------------------------------------------------
        # TIPOS DE SERVICIO
        # ---------------------------------------------------------

        self.fields["service_type"].queryset = (
            ServiceType.objects
            .filter(is_active=True)
            .order_by("name")
        )

        # ---------------------------------------------------------
        # PLANES
        # ---------------------------------------------------------

        self.fields["plan"].queryset = (
            Plan.objects
            .filter(is_active=True)
            .select_related("service_type")
            .order_by(
                "service_type__name",
                "name",
            )
        )

    # -------------------------------------------------------------
    # VALIDAR NÚMERO DE SERVICIO
    # -------------------------------------------------------------

    def clean_service_number(self):
        value = self.cleaned_data.get("service_number")

        if value is None:
            return value

        if value < 1:
            raise forms.ValidationError(
                "El número de servicio debe ser mayor o igual a 1."
            )

        return value

    # -------------------------------------------------------------
    # VALIDAR CICLO DE FACTURACIÓN
    # -------------------------------------------------------------

    def clean_billing_cycle(self):
        value = self.cleaned_data.get("billing_cycle")

        if value is None:
            return value

        if value < 1:
            raise forms.ValidationError(
                "El ciclo de facturación debe ser mayor o igual a 1."
            )

        return value

    # -------------------------------------------------------------
    # VALIDACIONES GENERALES
    # -------------------------------------------------------------

    def clean(self):
        cleaned_data = super().clean()

        address = cleaned_data.get("address")
        service_type = cleaned_data.get("service_type")
        plan = cleaned_data.get("plan")
        service_number = cleaned_data.get("service_number")

        # ---------------------------------------------------------
        # VALIDAR DIRECCIÓN DEL CLIENTE
        # ---------------------------------------------------------

        if self.customer and address:

            if address.customer_id != self.customer.pk:
                self.add_error(
                    "address",
                    "La dirección seleccionada no pertenece al cliente.",
                )

        # ---------------------------------------------------------
        # VALIDAR PLAN VS TIPO DE SERVICIO
        # ---------------------------------------------------------

        if service_type and plan:

            if plan.service_type_id != service_type.pk:
                self.add_error(
                    "plan",
                    (
                        "El plan seleccionado no pertenece "
                        "al tipo de servicio elegido."
                    ),
                )

        # ---------------------------------------------------------
        # VALIDAR NÚMERO DE SERVICIO
        # ---------------------------------------------------------

        if (
            self.customer
            and service_type
            and service_number
        ):
            exists = Subscription.objects.filter(
                customer=self.customer,
                service_type=service_type,
                service_number=service_number,
            ).exists()

            if exists:
                self.add_error(
                    "service_number",
                    (
                        "El cliente ya tiene registrado este "
                        "número de servicio para el tipo de "
                        "servicio seleccionado."
                    ),
                )

        return cleaned_data