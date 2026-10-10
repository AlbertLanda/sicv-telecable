import csv
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from .accounting_review import AccountingReviewForm, can_supervise
from .accounting_review_catalog import CASES, CASES_BY_CODE, CATALOG_VERSION
from .models import AccountingReviewNote


def csv_cell(value):
    value = str(value)
    if value and (value[0] in "\t\r\n" or value.lstrip().startswith(("=", "+", "-", "@"))):
        return "'" + value
    return value


class AccountingReviewView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = "payments.view_cash_closing"
    template_name = "reports/accounting_review.html"
    http_method_names = ["get", "post", "head", "options"]

    def dispatch(self, request, *args, **kwargs):
        if not settings.ACCOUNTING_REVIEW_ENABLED:
            raise Http404
        response = super().dispatch(request, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def reviewer(self):
        identifier = self.request.GET.get("revisor", str(self.request.user.pk))
        if identifier == str(self.request.user.pk):
            return self.request.user
        if not can_supervise(self.request.user):
            raise PermissionDenied
        if not identifier.isascii() or not identifier.isdecimal() or len(identifier) > 18:
            raise Http404
        return get_object_or_404(get_user_model().objects.filter(
            accounting_review_notes__catalog_version=CATALOG_VERSION).distinct(), pk=int(identifier))

    def selected_case(self):
        code = self.request.GET.get("caso", CASES[0]["code"])
        if code not in CASES_BY_CODE:
            raise Http404
        return CASES_BY_CODE[code]

    def review_notes(self, reviewer):
        return AccountingReviewNote.objects.filter(reviewer=reviewer, catalog_version=CATALOG_VERSION)

    def context(self, *, form=None):
        reviewer = self.reviewer()
        selected = self.selected_case()
        notes = list(self.review_notes(reviewer))
        latest = {}
        for note in notes:
            latest.setdefault(note.case_code, note)
        own_review = reviewer.pk == self.request.user.pk
        rows = []
        for item in CASES:
            note = latest.get(item["code"])
            rows.append({**item, "review": note,
                         "url": "?" + urlencode({"caso": item["code"], "revisor": reviewer.pk})})
        current = latest.get(selected["code"])
        if form is None:
            form = AccountingReviewForm(initial={
                "catalog_version": CATALOG_VERSION,
                "status": current.status if current else AccountingReviewNote.Status.PENDING,
                "missing_data": current.missing_data if current else "",
                "note": current.note if current else "",
            })
        reviewed = sum(bool(note and note.status != AccountingReviewNote.Status.PENDING)
                       for note in (latest.get(item["code"]) for item in CASES))
        reviewers = (get_user_model().objects.filter(accounting_review_notes__catalog_version=CATALOG_VERSION)
                     .distinct().order_by("username")) if can_supervise(self.request.user) else []
        return {
            **self.get_context_data(), "rows": rows, "selected": selected, "reviewer": reviewer,
            "own_review": own_review, "reviewers": reviewers, "form": form, "current": current,
            "history": [note for note in notes if note.case_code == selected["code"]][:5],
            "catalog_version": CATALOG_VERSION, "reviewed_count": reviewed,
            "pending_count": len(CASES) - reviewed,
            "changes_count": sum(bool(row["review"] and row["review"].status == AccountingReviewNote.Status.CHANGES)
                                 for row in rows),
            "export_url": "?" + urlencode({"export": "csv", "revisor": reviewer.pk}),
            "sample_links": self.sample_links(),
        }

    def sample_links(self):
        # El rol contable puede revisar TODO el catálogo sintético sin recibir
        # permisos adicionales sobre abonados, cobros o documentos reales.
        if not self.request.user.has_perms(("customers.change_customer", "payments.view_receipt")):
            return []
        from apps.audit.models import AuditEvent
        from apps.customers.models import Customer
        from apps.customers.qa_billing_examples import BILLING_SAMPLE_ROUTE
        from apps.organization.context_processors import get_active_branch

        branch = get_active_branch(self.request)
        if branch is None:
            return []
        event = AuditEvent.objects.filter(route_name=BILLING_SAMPLE_ROUTE, branch=branch).order_by("pk").first()
        if not event or not event.path.startswith("/customers/"):
            return []
        parts = event.path.strip("/").split("/")
        if len(parts) != 2 or not parts[1].isascii() or not parts[1].isdecimal():
            return []
        customer = Customer.objects.filter(pk=int(parts[1]), branch=branch).first()
        if customer is None:
            return []
        return [{"label": "Abrir comprobantes y muestras operativas de esta sede",
                 "url": reverse("payments:receipts", kwargs={"pk": customer.pk})}]

    def get(self, request, *args, **kwargs):
        context = self.context()
        if "export" in request.GET:
            if request.GET["export"] != "csv":
                raise Http404
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="revision-contable-qa.csv"'
            response.write("\ufeff")
            writer = csv.writer(response, delimiter=";")
            writer.writerow(["Versión", "Caso", "Área", "Cobertura", "Datos del ejemplo", "Resultado esperado", "Preguntas de revisión",
                             "Revisor", "Estado", "Dato faltante", "Observación", "Fecha (Lima)"])
            for row in context["rows"]:
                note = row["review"]
                writer.writerow([csv_cell(value) for value in [
                    CATALOG_VERSION, row["title"], row["area"], row["coverage"],
                    " | ".join(f"{label}: {value}" for label, value in row["fields"]), row["expected"],
                    " | ".join(row["checks"]), context["reviewer"].username,
                    note.get_status_display() if note else "Pendiente de revisar",
                    note.missing_data if note else "", note.note if note else "",
                    timezone.localtime(note.created_at).strftime("%d/%m/%Y %H:%M") if note else "",
                ]])
            return response
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        reviewer = self.reviewer()
        if reviewer.pk != request.user.pk:
            raise PermissionDenied
        selected = self.selected_case()
        form = AccountingReviewForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.context(form=form), status=400)
        AccountingReviewNote.objects.create(reviewer=request.user, case_code=selected["code"], **form.cleaned_data)
        messages.success(request, "Revisión guardada. Puedes continuar con otro caso; tu avance queda conservado.")
        return redirect(reverse("reports:accounting_review") + "?" + urlencode({"caso": selected["code"]}))
