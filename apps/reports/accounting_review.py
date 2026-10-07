"""Acceso QA y formulario para observaciones sobre ejemplos sintéticos."""
from django import forms
from django.conf import settings

from .accounting_review_catalog import CATALOG_VERSION
from .models import AccountingReviewNote


def review_available(user):
    return (settings.ACCOUNTING_REVIEW_ENABLED and user.is_authenticated
            and user.is_active and user.has_perm("payments.view_cash_closing"))


def can_supervise(user):
    return user.is_superuser or user.has_perms(("accounts.view_user", "audit.view_auditevent"))


class AccountingReviewForm(forms.Form):
    catalog_version = forms.TypedChoiceField(
        choices=[(CATALOG_VERSION, str(CATALOG_VERSION))], coerce=int, widget=forms.HiddenInput,
        initial=CATALOG_VERSION,
    )
    status = forms.ChoiceField(label="Resultado de tu revisión", choices=AccountingReviewNote.Status.choices,
                               widget=forms.Select(attrs={"class": "form-select"}))
    missing_data = forms.CharField(label="Dato o campo que falta", max_length=500, required=False,
                                   widget=forms.TextInput(attrs={"class": "form-control",
                                                                  "placeholder": "Ej.: nombre del depositante"}))
    note = forms.CharField(label="Observación y resultado esperado", max_length=2000, required=False,
                           widget=forms.Textarea(attrs={"class": "form-control", "rows": 4,
                                                        "placeholder": "Describe el caso con datos ficticios."}))

    def clean(self):
        data = super().clean()
        if data.get("status") in (AccountingReviewNote.Status.CHANGES, AccountingReviewNote.Status.NOT_APPLICABLE):
            if not data.get("note"):
                self.add_error("note", "Explica el ajuste necesario o por qué este caso no aplica.")
        if data.get("status") == AccountingReviewNote.Status.REVIEWED and data.get("missing_data"):
            self.add_error("status", "Si falta un dato, selecciona «Falta dato o ajuste».")
        return data
