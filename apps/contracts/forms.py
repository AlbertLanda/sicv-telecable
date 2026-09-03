import calendar
from datetime import date

from django import forms

from .models import Contract
from apps.accounts.models import User
from apps.services.models import Subscription
from apps.work_orders.models import OrderReason, WorkOrder


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


class InstallationWorkOrderForm(forms.Form):
    """
    Datos que ATC ingresa al generar la Orden de Instalación desde el
    resumen de contratación: observaciones, prioridad, motivo y vendedor.

    La instalación FTTH es siempre trabajo de campo. El formulario mantiene
    `attention_type` únicamente como dato explícito del contrato existente,
    pero restringido a FIELD para que ATC no pueda crear una instalación
    SYSTEM/NOC que después no aparecería en el canal técnico.

    No es un ModelForm de WorkOrder ni expone `subscription` ni `order_type`:
    create_installation_work_order() sigue siendo la fachada oficial.
    """

    detail = forms.CharField(
        required=False,
        label="Observaciones",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": (
                    "Observaciones operativas para el técnico..."
                ),
            }
        ),
    )

    priority = forms.ChoiceField(
        choices=WorkOrder.Priority.choices,
        required=False,
        initial=WorkOrder.Priority.NORMAL,
        label="Prioridad",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    reason = forms.ModelChoiceField(
        queryset=OrderReason.objects.none(),
        required=False,
        label="Motivo",
        empty_label="Sin motivo",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    # Una instalación FTTH que llega al técnico debe nacer en FIELD. Se deja
    # como selector de una sola opción para no romper la plantilla ni el
    # contrato actual de la vista, pero un POST manipulado con SYSTEM queda
    # invalidado por ChoiceField antes de llamar al dominio.
    attention_type = forms.ChoiceField(
        choices=[
            (WorkOrder.AttentionType.FIELD, "Campo"),
        ],
        required=False,
        initial=WorkOrder.AttentionType.FIELD,
        label="Tipo de atención",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    seller = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="Vendedor",
        empty_label="Sin vendedor",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Solo motivos activos del catálogo de INSTALACIÓN: el mismo
        # criterio de alcance que ya aplica WorkOrderCreateForm para el
        # resto de tipos de orden.
        self.fields["reason"].queryset = (
            OrderReason.objects
            .filter(
                order_type__code="INSTALLATION",
                is_active=True,
            )
            .order_by("name")
        )

        # Solo usuarios activos con rol Ventas: el mismo criterio que
        # _validate_seller exige en el servicio, para que el formulario
        # nunca ofrezca una opción que el servicio vaya a rechazar.
        self.fields["seller"].queryset = (
            User.objects
            .filter(
                role=User.Role.SALES,
                is_active=True,
            )
            .order_by("first_name", "last_name", "username")
        )
