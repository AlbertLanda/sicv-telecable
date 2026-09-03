from django import forms

from .models import Subscription, ServiceType, Plan
from apps.customers.models import CustomerAddress


class SubscriptionCreateForm(forms.ModelForm):
    tv_count = forms.IntegerField(
        required=False,
        min_value=1,
        label="Cantidad total de televisores",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "min": "1",
                "inputmode": "numeric",
            }
        ),
        help_text=(
            "Solo aplica a CABLE/DUO. Los primeros TV incluidos por el plan "
            "no generan anexo; desde el siguiente se calcula automáticamente."
        ),
    )

    class Meta:
        model = Subscription

        fields = [
            "address",
            "service_type",
            "plan",
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
            "billing_cycle": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                }
            ),
        }

        labels = {
            "address": "Domicilio del servicio",
            "service_type": "Tipo de servicio",
            "plan": "Plan",
            "billing_cycle": "Ciclo de facturación",
        }

    def __init__(self, *args, **kwargs):
        customer = kwargs.pop("customer", None)

        super().__init__(*args, **kwargs)

        self.customer = customer
        self.calculated_annex_count = 0

        # ---------------------------------------------------------
        # DIRECCIONES DEL CLIENTE
        # ---------------------------------------------------------

        self.fields["address"].queryset = CustomerAddress.objects.none()

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
        tv_count = cleaned_data.get("tv_count")

        # Dirección
        if self.customer and address:
            if address.customer_id != self.customer.pk:
                self.add_error(
                    "address",
                    "La dirección seleccionada no pertenece al cliente.",
                )
            elif not address.is_active:
                self.add_error(
                    "address",
                    "La dirección seleccionada no está activa.",
                )

        # Servicio
        if service_type and not service_type.is_active:
            self.add_error(
                "service_type",
                "El tipo de servicio seleccionado no está activo.",
            )

        # Plan
        if plan:
            if not plan.is_active:
                self.add_error(
                    "plan",
                    "El plan seleccionado no está activo.",
                )

            if service_type and plan.service_type_id != service_type.pk:
                self.add_error(
                    "plan",
                    (
                        "El plan seleccionado no pertenece "
                        "al tipo de servicio elegido."
                    ),
                )

        # ---------------------------------------------------------
        # ANEXOS DE TV
        #
        # ATC indica la cantidad TOTAL de televisores. El SICV calcula
        # cuántos exceden los incluidos por el plan. Internet puro no
        # admite este dato ni por UI ni mediante un POST manipulado.
        # ---------------------------------------------------------

        self.calculated_annex_count = 0

        if service_type and plan and service_type.supports_tv_annexes:
            if tv_count is None:
                self.add_error(
                    "tv_count",
                    (
                        "Indique la cantidad total de televisores que "
                        "recibirán señal de cable."
                    ),
                )
            else:
                self.calculated_annex_count = max(
                    tv_count - plan.included_tv_points,
                    0,
                )

        elif tv_count not in (None, 0):
            self.add_error(
                "tv_count",
                (
                    "La cantidad de televisores solo aplica a servicios "
                    "CABLE/DUO que permiten anexos de TV."
                ),
            )

        # ---------------------------------------------------------
        # EVITAR SERVICIO OPERATIVO DUPLICADO EN EL MISMO DOMICILIO
        #
        # Una nueva suscripción sí puede corresponder a otro domicilio o
        # a otro tipo de servicio. Lo que no se permite por defecto es
        # abrir otra instancia del mismo servicio en el mismo domicilio
        # mientras exista una vigente/no cancelada.
        # ---------------------------------------------------------

        if self.customer and address and service_type:
            exists = (
                Subscription.objects
                .filter(
                    customer=self.customer,
                    address=address,
                    service_type=service_type,
                    is_active=True,
                )
                .exclude(status=Subscription.Status.CANCELLED)
                .exists()
            )

            if exists:
                self.add_error(
                    "service_type",
                    (
                        "El cliente ya tiene este tipo de servicio abierto "
                        "en el domicilio seleccionado. Use otro domicilio, "
                        "otro servicio o cierre/cancele el anterior."
                    ),
                )

        return cleaned_data
