from django import forms

from .models import Contract
from apps.services.models import Subscription


class ContractCreateForm(forms.ModelForm):

    class Meta:
        model = Contract

        fields = [
            "contract_number",
            "subscription",
            "start_date",
            "end_date",
            "status",
            "notes",
        ]

        widgets = {
            "contract_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ej. CONT-000001",
                    "maxlength": "30",
                }
            ),
            "subscription": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "start_date": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "end_date": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "status": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Observaciones del contrato...",
                }
            ),
        }

        labels = {
            "contract_number": "Número de contrato",
            "subscription": "Suscripción",
            "start_date": "Fecha de inicio",
            "end_date": "Fecha de finalización",
            "status": "Estado",
            "notes": "Observaciones",
        }

    def __init__(self, *args, **kwargs):
        customer = kwargs.pop("customer", None)

        super().__init__(*args, **kwargs)

        self.customer = customer

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

    def clean_contract_number(self):
        value = self.cleaned_data.get("contract_number")

        if value:
            value = value.strip().upper()

        return value

    def clean(self):
        cleaned_data = super().clean()

        subscription = cleaned_data.get("subscription")
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        # ---------------------------------------------------------
        # VALIDAR SUSCRIPCIÓN DEL CLIENTE
        # ---------------------------------------------------------

        if self.customer and subscription:

            if subscription.customer_id != self.customer.pk:
                self.add_error(
                    "subscription",
                    "La suscripción seleccionada no pertenece al cliente.",
                )

        # ---------------------------------------------------------
        # VALIDAR FECHAS
        # ---------------------------------------------------------

        if start_date and end_date:

            if end_date < start_date:
                self.add_error(
                    "end_date",
                    (
                        "La fecha de finalización no puede "
                        "ser anterior a la fecha de inicio."
                    ),
                )

        # ---------------------------------------------------------
        # EVITAR CONTRATO DUPLICADO
        # ---------------------------------------------------------

        if subscription:

            exists = Contract.objects.filter(
                subscription=subscription,
                is_active=True,
            ).exists()

            if exists:
                self.add_error(
                    "subscription",
                    (
                        "La suscripción seleccionada ya tiene "
                        "un contrato activo registrado."
                    ),
                )

        return cleaned_data