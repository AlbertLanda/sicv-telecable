import uuid
from decimal import Decimal

from django import forms

from .cash import DENOMINATIONS, MANUAL_KINDS
from .models import CashEntry, Issuer


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-select" if isinstance(field.widget, forms.Select) else "form-control")


class OpenCashForm(StyledForm):
    opening_amount = forms.DecimalField(label="Fondo inicial en efectivo (S/)", max_digits=12, decimal_places=2, min_value=0)
    reason = forms.CharField(label="Origen del fondo o explicación del cambio", max_length=300, required=False,
                             help_text="En la primera apertura es obligatorio. No incluya los cobros de hoy.")


class CashMovementForm(StyledForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    kind = forms.ChoiceField(label="Movimiento", choices=[(key, label) for key, label in CashEntry.Kind.choices if key in MANUAL_KINDS])
    issuer_id = forms.ModelChoiceField(label="Empresa", queryset=Issuer.objects.none())
    amount = forms.DecimalField(label="Importe en efectivo (S/)", min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    description = forms.CharField(label="Motivo y descripción", max_length=300)
    document_type = forms.CharField(label="Tipo de sustento (gasto)", max_length=50, required=False, help_text="Recibo, factura o sustento interno, según corresponda.")
    document_number = forms.CharField(label="Serie/número de sustento (gasto)", max_length=100, required=False)
    bank = forms.CharField(label="Banco de destino (depósito)", max_length=100, required=False)
    account = forms.CharField(label="Cuenta de destino (depósito)", max_length=100, required=False)
    reference = forms.CharField(label="Operación bancaria (depósito) / referencia", max_length=100, required=False)

    def __init__(self, *args, office, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["issuer_id"].queryset = Issuer.objects.filter(
            is_active=True, sequences__is_active=True, sequences__offices=office).distinct()


class CashCountForm(StyledForm):
    explanation = forms.CharField(label="Explicación de diferencia / observaciones", max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for denomination in DENOMINATIONS:
            self.fields[f"count_{denomination}"] = forms.IntegerField(
                label=f"S/ {denomination}", min_value=0, max_value=1000000, initial=0,
                widget=forms.NumberInput(attrs={"class": "form-control", "inputmode": "numeric", "data-denomination": denomination}))
        self.order_fields([f"count_{value}" for value in DENOMINATIONS] + ["explanation"])

    def counts(self):
        return {value: self.cleaned_data[f"count_{value}"] for value in DENOMINATIONS}


class CashReviewForm(StyledForm):
    close_id = forms.IntegerField(widget=forms.HiddenInput)
    decision = forms.ChoiceField(label="Decisión", choices=[("APPROVED", "Aprobar cierre"), ("RETURNED", "Devolver para corrección")])
    reason = forms.CharField(label="Comentario de revisión", max_length=500, widget=forms.Textarea(attrs={"rows": 2}))


class CashReversalForm(StyledForm):
    entry_id = forms.IntegerField(label="Número de movimiento que se corrige", min_value=1)
    reason = forms.CharField(label="Motivo de reversión", max_length=300)
