import uuid

from django import forms
from django.utils import timezone

from apps.payments.models import Charge, Issuer
from .models import DocumentType, FiscalProfile, OseConnection, OseSimulation


class ChargeChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, charge):
        return f"{charge.description} · {charge.period_label or 'Sin periodo'} · {charge.currency} {charge.amount:.2f}"


class DraftForm(forms.Form):
    issuer = forms.ModelChoiceField(label="Empresa emisora", queryset=Issuer.objects.filter(is_active=True))
    document_type = forms.ChoiceField(label="Tipo propuesto", choices=DocumentType.choices)
    proposed_issue_date = forms.DateField(
        label="Fecha propuesta", initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    charges = ChargeChoiceField(label="Cargos para revisión", queryset=Charge.objects.none(), widget=forms.CheckboxSelectMultiple)
    request_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["charges"].queryset = Charge.objects.filter(customer=customer).exclude(status=Charge.Status.CANCELLED)
        if not self.is_bound:
            self.initial["request_key"] = uuid.uuid4()
        for name in ("issuer", "document_type", "proposed_issue_date"):
            self.fields[name].widget.attrs["class"] = "form-control"


class FiscalProfileForm(forms.ModelForm):
    document_types = forms.MultipleChoiceField(
        label="Documentos previstos", choices=DocumentType.choices,
        required=False, widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = FiscalProfile
        fields = ["modality", "provider_name", "document_types", "billing_trigger",
                  "tax_rules_confirmed", "receiver_rules_confirmed", "confirmation_reference"]
        widgets = {"confirmation_reference": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                field.widget.attrs["class"] = "form-control"


class OseConnectionForm(forms.ModelForm):
    class Meta:
        model = OseConnection
        fields = ["mode", "provider_name", "test_endpoint", "production_endpoint",
                  "username_setting", "password_setting", "certificate_setting", "certificate_password_setting"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-control"
            if name.endswith("_setting"):
                field.help_text = "Nombre de una variable SICV_OSE_… del servidor. Aquí no se guardan secretos."


class OseSimulationForm(forms.Form):
    scenario = forms.ChoiceField(label="Escenario de prueba", choices=OseSimulation.Scenario.choices,
                                 widget=forms.Select(attrs={"class": "form-select"}))
    request_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["request_key"] = uuid.uuid4()
