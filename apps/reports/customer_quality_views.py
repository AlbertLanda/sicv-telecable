from urllib.parse import urlencode

from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from django.views.generic import TemplateView

from apps.organization.context_processors import get_active_branch

from .customer_quality import ISSUES, any_issue, customers_with_quality_flags, issues_for, quality_summary


class CustomerQualityFilterForm(forms.Form):
    issue = forms.ChoiceField(
        label="Revisión",
        choices=(("all", "Con alguna alerta"),) + tuple((key, label) for key, label, _ in ISSUES)
        + (("clear", "Sin alertas detectadas"), ("everyone", "Todos los abonados")),
    )
    status = forms.ChoiceField(
        label="Estado del abonado",
        choices=(("all", "Activos e inactivos"), ("active", "Activos"), ("inactive", "Inactivos")),
    )
    q = forms.CharField(label="Buscar", required=False, max_length=120)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select" if isinstance(field, forms.ChoiceField) else "form-control"
        self.fields["q"].widget.attrs["placeholder"] = "Código, nombre o documento"


class CustomerQualityView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """ATC/Administración revisan el padrón que ya pueden mantener."""

    template_name = "reports/customer_quality.html"
    permission_required = "customers.change_customer"
    http_method_names = ["get", "head", "options"]

    def get(self, request, *args, **kwargs):
        branch = get_active_branch(request)
        params = request.GET.copy()
        for key, value in {"issue": "all", "status": "all"}.items():
            if key not in params:
                params[key] = value
        form = CustomerQualityFilterForm(params)
        valid = form.is_valid()
        if branch is None:
            form.add_error(None, "Selecciona una sede activa en la barra superior.")
            valid = False
        context = self.get_context_data(form=form, branch=branch, consulted_at=timezone.now(), checks=ISSUES)
        if valid:
            fields = form.cleaned_data
            customers = customers_with_quality_flags(branch)
            if fields["status"] != "all":
                customers = customers.filter(is_active=fields["status"] == "active")
            if fields["q"]:
                term = fields["q"]
                customers = customers.filter(
                    Q(code__icontains=term) | Q(document_number__icontains=term)
                    | Q(first_name__icontains=term) | Q(paternal_surname__icontains=term)
                    | Q(maternal_surname__icontains=term) | Q(business_name__icontains=term)
                )
            # Los contadores conservan el estado y la búsqueda. Elegir una
            # alerta recorta solo la lista; un abonado puede tener varias.
            summary = quality_summary(customers)
            summary["clear"] = summary["total"] - summary["flagged"]
            issue = fields["issue"]
            if issue == "all":
                customers = customers.filter(any_issue())
            elif issue == "clear":
                customers = customers.exclude(any_issue())
            elif issue != "everyone":
                customers = customers.filter(**{f"issue_{issue}": True})
            page = Paginator(customers, 25).get_page(request.GET.get("page"))
            query = {"issue": issue, "status": fields["status"], "q": fields["q"]}
            context.update(
                summary=summary,
                cards=[{
                    "label": label, "count": summary[key],
                    "url": "?" + urlencode({**query, "issue": key}),
                } for key, label, _ in ISSUES],
                rows=[{"customer": customer, "issues": issues_for(customer)} for customer in page],
                page_obj=page,
                page_query=urlencode(query),
            )
        response = self.render_to_response(context, status=200 if valid else 400)
        response["Cache-Control"] = "private, no-store"
        return response
