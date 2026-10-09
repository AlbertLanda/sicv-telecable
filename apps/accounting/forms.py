from datetime import date

from django import forms
from django.contrib.auth import get_user_model

from apps.payments.models import Issuer
from .access import available_issuers
from .models import ImportBatch


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-check-input" if isinstance(field.widget, forms.CheckboxInput)
                                           else "form-select" if isinstance(field.widget, forms.Select) else "form-control")


class PeriodField(forms.CharField):
    def __init__(self, **kwargs):
        super().__init__(label="Periodo", max_length=7, widget=forms.TextInput(attrs={"type": "month"}), **kwargs)

    def clean(self, value):
        raw = super().clean(value)
        try:
            parsed = date.fromisoformat(raw + "-01")
            if not 2000 <= parsed.year <= 2100:
                raise ValueError
            return parsed
        except ValueError:
            raise forms.ValidationError("Seleccione un periodo entre 2000 y 2100.") from None


class ScopeForm(StyledForm):
    issuer = forms.ModelChoiceField(label="Empresa / RUC", queryset=Issuer.objects.none())
    period = PeriodField()

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["issuer"].queryset = available_issuers(user)
        self.fields["issuer"].label_from_instance = lambda obj: f"{obj.business_name} · {obj.ruc}"


class ImportForm(ScopeForm):
    source = forms.ChoiceField(label="Fuente", choices=ImportBatch.Source.choices)
    file = forms.FileField(label="Archivo", widget=forms.FileInput(attrs={"accept": ".xlsx,.csv"}))
    confirm = forms.BooleanField(label="Confirmo que corresponde a la empresa y periodo seleccionados; el OSIPTEL está expresado en soles.")


class ReviewForm(StyledForm):
    note = forms.CharField(label="Motivo / observación", max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))
    line = forms.TypedChoiceField(label="Línea a reclasificar (opcional)", coerce=int, empty_value=None, required=False)
    concept = forms.CharField(label="Concepto OSIPTEL revisado", max_length=160, required=False)
    technology = forms.CharField(label="Tecnología revisada", max_length=100, required=False)

    def __init__(self, *args, document, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["line"].choices = [("", "Solo registrar observación")] + [
            (line.pk, f"Fila {line.source_row}: {line.description[:80]}") for line in document.lines.all()]

    def clean(self):
        data = super().clean()
        if data.get("line") and (not data.get("concept") or not data.get("technology")):
            raise forms.ValidationError("Para reclasificar complete concepto y tecnología. Los importes originales se conservan.")
        if not data.get("line") and (data.get("concept") or data.get("technology")):
            raise forms.ValidationError("Seleccione la línea a reclasificar.")
        return data


class AccessForm(StyledForm):
    user = forms.ModelChoiceField(label="Usuario contable", queryset=get_user_model().objects.none())
    issuer = forms.ModelChoiceField(label="Empresa", queryset=Issuer.objects.none())
    enabled = forms.BooleanField(label="Acceso habilitado", required=False, initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = get_user_model().objects.filter(is_active=True, role="ACCOUNTING")
        self.fields["issuer"].queryset = Issuer.objects.filter(is_active=True)
