from datetime import date
from urllib.parse import urlencode

from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView
from django.db.models import Sum

from apps.organization.context_processors import get_active_branch
from apps.organization.models import Branch
from apps.payments.models import ZERO

from .dashboard import DashboardData

DETAILS = {
    "active": "Abonados activos",
    "income": "Pagos confirmados",
    "debt": "Abonados con cartera vencida",
    "orders": "Órdenes pendientes",
}
AGES = {
    "debt": (
        ("all", "Toda la cartera"),
        ("1_30", "1 a 30 días"),
        ("31_60", "31 a 60 días"),
        ("61_plus", "61 días o más"),
    ),
    "orders": (
        ("all", "Todas las pendientes"),
        ("over_48", "Más de 48 horas"),
        ("0_24", "Hasta 24 horas"),
        ("24_48", "Más de 24 y hasta 48 horas"),
    ),
}


class DashboardFilterForm(forms.Form):
    scope = forms.ChoiceField(
        label="Alcance",
        choices=(("current", "Sede actual"), ("consolidated", "Consolidado")),
    )
    branch = forms.ModelChoiceField(
        label="Sede",
        queryset=Branch.objects.none(),
        required=False,
        empty_label="Todas las sedes",
    )
    month = forms.RegexField(
        label="Mes de recaudación",
        regex=r"^\d{4}-\d{2}$",
        widget=forms.TextInput(attrs={"type": "month"}),
    )
    q = forms.CharField(label="Buscar", max_length=120, required=False)
    per_page = forms.TypedChoiceField(
        label="Filas", choices=((20, "20"), (50, "50"), (100, "100")), coerce=int
    )
    age = forms.ChoiceField(label="Antigüedad", choices=(("all", "Todas"),))

    def __init__(self, *args, active_branch, can_consolidate, kind=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.active_branch = active_branch
        self.can_consolidate = can_consolidate
        branches = Branch.objects.filter(is_active=True)
        self.fields["branch"].queryset = (
            branches
            if can_consolidate
            else branches.filter(pk=getattr(active_branch, "pk", None))
        )
        if not can_consolidate:
            self.fields["scope"].choices = (("current", "Sede actual"),)
        self.fields["age"].choices = AGES.get(kind, (("all", "Todas"),))
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-select"
                if isinstance(field, forms.ChoiceField)
                else "form-control"
            )
        self.fields["q"].widget.attrs["placeholder"] = "Código, nombre o documento"

    def clean_month(self):
        value = self.cleaned_data["month"]
        try:
            month = date.fromisoformat(value + "-01")
        except ValueError:
            raise forms.ValidationError("Selecciona un mes válido.")
        if not 2000 <= month.year <= 2100:
            raise forms.ValidationError("El año debe estar entre 2000 y 2100.")
        return month

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("scope") == "current":
            if self.active_branch is None:
                raise forms.ValidationError(
                    "Selecciona una sede activa en la barra superior."
                )
            if cleaned.get("branch") and cleaned["branch"].pk != self.active_branch.pk:
                raise forms.ValidationError(
                    "La sede del filtro no coincide con la sede actual. Usa Consolidado para elegir otra."
                )
        return cleaned


class DashboardMixin(LoginRequiredMixin, PermissionRequiredMixin):
    permission_required = "organization.view_operational_dashboard"

    def setup_filters(self, kind=None):
        can_consolidate = self.request.user.has_perm(
            "organization.view_consolidated_dashboard"
        )
        if self.request.GET.get("scope") == "consolidated" and not can_consolidate:
            raise PermissionDenied
        params = self.request.GET.copy()
        defaults = {
            "scope": "current",
            "month": timezone.localdate().strftime("%Y-%m"),
            "per_page": "20",
            "age": "all",
        }
        for key, value in defaults.items():
            if key not in params:
                params[key] = value
        form = DashboardFilterForm(
            params,
            active_branch=get_active_branch(self.request),
            can_consolidate=can_consolidate,
            kind=kind,
        )
        self.filter_form = form
        self.can_consolidate = can_consolidate
        self.data = None
        if form.is_valid():
            fields = form.cleaned_data
            if fields["scope"] == "current":
                branches = [form.active_branch]
            elif fields["branch"]:
                branches = [fields["branch"]]
            else:
                branches = list(form.fields["branch"].queryset)
            self.data = DashboardData(branches=branches, month=fields["month"])

    def query_params(self, **overrides):
        fields = self.filter_form.cleaned_data
        params = {"scope": fields["scope"], "month": fields["month"].strftime("%Y-%m")}
        if fields.get("branch"):
            params["branch"] = fields["branch"].pk
        params.update(overrides)
        return urlencode(params)

    def detail_url(self, kind, **overrides):
        return (
            reverse("reports:dashboard_detail", args=[kind])
            + "?"
            + self.query_params(**overrides)
        )

    def base_context(self):
        return {
            "form": self.filter_form,
            "can_consolidate": self.can_consolidate,
            "dashboard_data": self.data,
            "scope_label": (
                ", ".join(branch.name for branch in self.data.branches)
                if self.data
                else ""
            ),
            "current_scope": self.filter_form.data.get("scope"),
        }

    def render_checked(self, context):
        response = self.render_to_response(context)
        response["Cache-Control"] = "private, no-store"
        if self.data is None:
            response.status_code = 400
        return response


class OperationalDashboardView(DashboardMixin, TemplateView):
    template_name = "reports/dashboard.html"

    def get(self, request, *args, **kwargs):
        self.setup_filters()
        context = self.get_context_data(**self.base_context())
        if self.data:
            context["summary"] = self.data.summary()
            context["links"] = {
                kind: self.detail_url(
                    kind, **({"age": "over_48"} if kind == "orders" else {})
                )
                for kind in DETAILS
            }
            context["all_orders_url"] = self.detail_url("orders")
            if len(self.data.branches) > 1:
                context["branch_comparison"] = [
                    {
                        "branch": branch,
                        "summary": DashboardData(
                            branches=[branch], month=self.data.month, now=self.data.now
                        ).summary(),
                        "url": reverse("reports:dashboard")
                        + "?"
                        + self.query_params(branch=branch.pk),
                    }
                    for branch in self.data.branches
                ]
            trend = self.data.trend()
            for row in trend:
                row["url"] = self.detail_url(
                    "income", month=row["month"].strftime("%Y-%m")
                )
            context["trend"] = trend
            context["debt_ages"] = [
                {
                    "label": label,
                    "url": self.detail_url("debt", age=age),
                    "count": self.data.debtors(age).count(),
                    "amount": self.data.debtors(age).aggregate(total=Sum("balance"))[
                        "total"
                    ]
                    or ZERO,
                }
                for age, label in AGES["debt"][1:]
            ]
        return self.render_checked(context)


class OperationalDashboardDetailView(DashboardMixin, TemplateView):
    template_name = "reports/dashboard_detail.html"

    def get(self, request, kind, *args, **kwargs):
        if kind not in DETAILS:
            raise Http404
        self.setup_filters(kind)
        context = self.get_context_data(
            **self.base_context(), kind=kind, title=DETAILS[kind]
        )
        if self.data:
            fields = self.filter_form.cleaned_data
            queryset = self.data.detail_queryset(
                kind, query=fields["q"], age=fields["age"]
            )
            page = Paginator(queryset, fields["per_page"]).get_page(
                request.GET.get("page")
            )
            if kind == "orders" and fields["age"] == "over_48":
                context["title"] = "Órdenes pendientes con más de 48 horas"
            context.update(
                page_obj=page,
                rows=self.data.display_rows(kind, list(page.object_list), request.user),
                total_amount=None,
                has_age=kind in AGES,
                panel_url=reverse("reports:dashboard") + "?" + self.query_params(),
            )
            if kind in ("income", "debt"):
                context["total_amount"] = (
                    queryset.aggregate(
                        total=Sum("amount" if kind == "income" else "balance")
                    )["total"]
                    or ZERO
                )
            context["page_query"] = self.query_params(
                q=fields["q"], per_page=fields["per_page"], age=fields["age"]
            )
        return self.render_checked(context)
