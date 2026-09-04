from django import forms
from django.core.exceptions import ValidationError

from apps.customers.models import CustomerAddress

from .commercial import build_commercial_quote
from .models import Plan, ServiceType, Subscription


class SubscriptionCreateForm(forms.ModelForm):
    # Compatibilidad con POST antiguos: el correlativo real lo genera el servidor.
    service_number = forms.IntegerField(
        required=False,
        min_value=1,
        error_messages={
            "min_value": "El número de servicio debe ser mayor o igual a 1.",
        },
        widget=forms.HiddenInput(),
    )

    tv_count = forms.IntegerField(
        required=False,
        min_value=1,
        label="Televisores disponibles para habilitar en esta instalación",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "min": "1",
                "inputmode": "numeric",
            }
        ),
        help_text=(
            "Solo CABLE/DUO. La cortesía se consume únicamente durante esta "
            "instalación; una TV que no esté disponible hoy no queda reservada."
        ),
    )

    class Meta:
        model = Subscription
        fields = ["address", "service_type", "plan", "billing_cycle"]
        widgets = {
            "address": forms.Select(attrs={"class": "form-select"}),
            "service_type": forms.Select(attrs={"class": "form-select"}),
            "plan": forms.Select(attrs={"class": "form-select"}),
            "billing_cycle": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
        }
        labels = {
            "address": "Domicilio del servicio",
            "service_type": "Tipo de servicio",
            "plan": "Plan",
            "billing_cycle": "Ciclo de facturación legado",
        }

    def __init__(self, *args, **kwargs):
        customer = kwargs.pop("customer", None)
        super().__init__(*args, **kwargs)

        self.customer = customer
        self.calculated_annex_count = 0
        self.calculated_initial_courtesy_count = 0
        self.selected_quote = None

        self.fields["address"].queryset = CustomerAddress.objects.none()
        if customer is not None:
            self.fields["address"].queryset = (
                CustomerAddress.objects
                .filter(customer=customer, is_active=True)
                .select_related("zone", "zone__branch", "customer__branch")
                .order_by("-is_primary", "address")
            )

        self.fields["service_type"].queryset = (
            ServiceType.objects.filter(is_active=True).order_by("name")
        )
        self.fields["plan"].queryset = (
            Plan.objects
            .filter(is_active=True)
            .select_related("service_type", "billing_policy")
            .order_by("-generation", "commercial_category", "service_type__name", "speed_mbps", "name")
        )

    def clean_service_number(self):
        value = self.cleaned_data.get("service_number")
        if value is not None and value < 1:
            raise forms.ValidationError(
                "El número de servicio debe ser mayor o igual a 1."
            )
        return value

    def clean_billing_cycle(self):
        value = self.cleaned_data.get("billing_cycle")
        if value is not None and value < 1:
            raise forms.ValidationError(
                "El ciclo de facturación debe ser mayor o igual a 1."
            )
        return value

    def clean(self):
        cleaned_data = super().clean()
        address = cleaned_data.get("address")
        service_type = cleaned_data.get("service_type")
        plan = cleaned_data.get("plan")
        tv_count = cleaned_data.get("tv_count")

        if self.customer and address:
            if address.customer_id != self.customer.pk:
                self.add_error("address", "La dirección seleccionada no pertenece al cliente.")
            elif not address.is_active:
                self.add_error("address", "La dirección seleccionada no está activa.")

        if service_type and not service_type.is_active:
            self.add_error("service_type", "El tipo de servicio seleccionado no está activo.")

        if plan:
            if not plan.is_active:
                self.add_error("plan", "El plan seleccionado no está activo.")
            if service_type and plan.service_type_id != service_type.pk:
                self.add_error(
                    "plan",
                    "El plan seleccionado no pertenece al tipo de servicio elegido.",
                )

        # TV: el máximo del plan es una cortesía de ALTA, no un saldo permanente.
        self.calculated_annex_count = 0
        self.calculated_initial_courtesy_count = 0

        if service_type and plan and service_type.supports_tv_annexes:
            if tv_count is None:
                self.add_error(
                    "tv_count",
                    "Indique cuántos televisores están disponibles para habilitar durante esta instalación.",
                )
            else:
                courtesy_limit = plan.initial_tv_courtesy_limit
                self.calculated_initial_courtesy_count = min(tv_count, courtesy_limit)
                self.calculated_annex_count = max(tv_count - courtesy_limit, 0)
        elif tv_count not in (None, 0):
            self.add_error(
                "tv_count",
                "La cantidad de televisores solo aplica a CABLE/DUO.",
            )

        # Evita por defecto dos servicios abiertos iguales en el mismo domicilio.
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
                        "El cliente ya tiene este tipo de servicio abierto en el "
                        "domicilio seleccionado. Use otro domicilio, otro servicio "
                        "o cierre/cancele el anterior."
                    ),
                )
                if self.data.get("service_number") not in (None, ""):
                    self.add_error(
                        "service_number",
                        (
                            "El cliente ya tiene registrado este número de servicio "
                            "para el tipo de servicio seleccionado."
                        ),
                    )

        # Cotización comercial centralizada: cobertura + tarifa + política.
        if address and plan and service_type and plan.service_type_id == service_type.pk:
            try:
                self.selected_quote = build_commercial_quote(plan=plan, address=address)
            except ValidationError as exc:
                self.add_error("plan", " ".join(exc.messages))

        return cleaned_data
