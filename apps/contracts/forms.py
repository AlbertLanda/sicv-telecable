import calendar
from datetime import date

from django import forms

from .models import Contract
from apps.services.models import Subscription


# Duración mínima del contrato, en meses (mejora solicitada 02/09).
# Un contrato FTTH no puede cerrarse con una vigencia menor a medio año:
# se valida aquí, en el formulario, y no en el modelo, porque end_date
# sigue siendo opcional (null=True, blank=True) para los contratos sin
# fecha de finalización definida -esos no entran a esta validación-.
MINIMUM_CONTRACT_DURATION_MONTHS = 6


def _add_months(source_date, months):
    """
    Suma meses calendario a una fecha, sin depender de python-dateutil
    (no está en requirements.txt). Si el día de origen no existe en el
    mes de destino (p. ej. 31 de enero + 1 mes) se ajusta al último día
    de ese mes, igual que relativedelta.
    """

    month_index = source_date.month - 1 + months

    year = source_date.year + month_index // 12
    month = month_index % 12 + 1

    day = min(
        source_date.day,
        calendar.monthrange(year, month)[1],
    )

    return date(year, month, day)


class ContractCreateForm(forms.ModelForm):

    class Meta:
        model = Contract

        fields = [
            "subscription",
            "start_date",
            "end_date",
            "notes",
        ]

        widgets = {
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
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Observaciones del contrato...",
                }
            ),
        }

        labels = {
            "subscription": "Suscripción",
            "start_date": "Fecha de inicio",
            "end_date": "Fecha de finalización",
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
                    status=Subscription.Status.PRESALE,
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
        # VALIDAR SUSCRIPCIÓN ACTIVA
        # ---------------------------------------------------------

        if subscription:

            if not subscription.is_active:
                self.add_error(
                    "subscription",
                    "La suscripción seleccionada no está activa.",
                )

            if subscription.status != Subscription.Status.PRESALE:
                self.add_error(
                    "subscription",
                    (
                        "Solo se puede registrar un contrato para "
                        "una suscripción en estado Preventa."
                    ),
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

            else:
                minimum_end_date = _add_months(
                    start_date,
                    MINIMUM_CONTRACT_DURATION_MONTHS,
                )

                if end_date < minimum_end_date:
                    self.add_error(
                        "end_date",
                        (
                            "El contrato debe tener una vigencia "
                            f"mínima de {MINIMUM_CONTRACT_DURATION_MONTHS} "
                            "meses. Con esta fecha de inicio, la fecha "
                            "de finalización debe ser "
                            f"{minimum_end_date:%d/%m/%Y} o posterior."
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