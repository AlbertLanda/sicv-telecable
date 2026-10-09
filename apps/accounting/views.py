import csv
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Max
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.audit.models import AuditEvent
from .access import available_issuers, require_access
from .exporters import export_workbook
from .forms import AccessForm, ImportForm, ReviewForm, ScopeForm
from .importers import FLAGS, RVIE_HEADERS, import_report
from .models import CompanyAccess, Document, ImportBatch, Review
from .reconciliation import RESULTS, classified_lines, compare, osiptel_summary, totals_by_currency


def protected(permission="accounting.view_workspace"):
    def decorate(view):
        return never_cache(login_required(permission_required(permission, raise_exception=True)(view)))
    return decorate


def numeric_param(value):
    if not str(value).isascii() or not str(value).isdecimal() or len(str(value)) > 18:
        raise Http404
    return int(value)


def scope_url(issuer, period, **extra):
    return reverse("accounting:workspace") + "?" + urlencode({"issuer": issuer.pk, "period": period.strftime("%Y-%m"), **extra})


def selected_batches(params, issuer, period):
    scope = ImportBatch.objects.filter(issuer=issuer, period=period, issuer_ruc=issuer.ruc)
    result = []
    for name, source in (("legacy", "OSIPTEL"), ("rvie", "RVIE")):
        batches = scope.filter(source=source).select_related("imported_by")
        if name in params:
            identifier = numeric_param(params[name])
            result.append(get_object_or_404(batches, pk=identifier) if identifier else None)
        else:
            result.append(batches.first())
    return result


@protected()
@require_http_methods(["GET"])
def workspace(request):
    issuers = available_issuers(request.user)
    newest = ImportBatch.objects.filter(issuer__in=issuers).first()
    first = issuers.first()
    data = request.GET or {"issuer": newest.issuer_id if newest else first.pk if first else "",
                           "period": (newest.period if newest else timezone.localdate()).strftime("%Y-%m")}
    form = ScopeForm(data, user=request.user)
    context = {"form": form, "has_issuers": issuers.exists()}
    if not form.is_valid():
        return render(request, "accounting/workspace.html", context, status=400 if request.GET else 200)
    issuer, period = form.cleaned_data["issuer"], form.cleaned_data["period"]
    legacy, rvie = selected_batches(request.GET, issuer, period)
    rows = compare(legacy, rvie)
    selected_ids = [b.pk for b in (legacy, rvie) if b]
    last_review = Review.objects.filter(document__batch_id__in=selected_ids).aggregate(last=Max("pk"))["last"] or 0
    cutoff = numeric_param(request.GET["reviews"]) if "reviews" in request.GET else last_review
    params = {"issuer": issuer.pk, "period": period.strftime("%Y-%m"), "legacy": legacy.pk if legacy else 0,
              "rvie": rvie.pk if rvie else 0, "reviews": cutoff}
    if "export" in request.GET:
        if request.GET["export"] != "xlsx":
            raise Http404
        # A pinned review version cannot include a future annotation on repeat.
        if cutoff > last_review:
            raise Http404
        return export_workbook(issuer=issuer, period=period, legacy=legacy, rvie=rvie, rows=rows, cutoff=cutoff)
    result = request.GET.get("result", "")
    query = request.GET.get("q", "").strip()[:100].casefold()
    if result and result not in RESULTS and result != "ATTENTION":
        raise Http404
    filtered = rows
    if result == "ATTENTION":
        filtered = [row for row in rows if row["attention"]]
    elif result:
        filtered = [row for row in rows if row["result"] == result]
    if query:
        filtered = [row for row in filtered if query in (row["document"].label + " " + row["document"].receiver_name + " " + row["document"].receiver_document).casefold()]
    lines = classified_lines(legacy, cutoff=cutoff)
    context.update({"issuer": issuer, "period": period, "legacy": legacy, "rvie": rvie,
        "page": Paginator(filtered, 50).get_page(request.GET.get("page")), "row_count": len(rows),
        "attention_count": sum(row["attention"] for row in rows),
        "difference_count": sum(row["result"] == "DIFFERENCE" for row in rows),
        "match_count": sum(row["result"] == "MATCH" for row in rows),
        "legacy_totals": totals_by_currency(row["local"] for row in rows if row["local"]),
        "rvie_totals": totals_by_currency(row["rvie"] for row in rows if row["rvie"]),
        "summary": osiptel_summary(lines), "results": RESULTS.items(), "selected_result": result, "query": request.GET.get("q", "")[:100],
        "versions": ImportBatch.objects.filter(issuer=issuer, period=period).select_related("imported_by")[:20],
        "pinned": params, "page_query": urlencode({**params, "result": result, "q": request.GET.get("q", "")[:100]}),
        "export_url": "?" + urlencode({**params, "export": "xlsx"}),
        "import_url": reverse("accounting:import") + "?" + urlencode({"issuer": issuer.pk, "period": period.strftime("%Y-%m")})})
    return render(request, "accounting/workspace.html", context)


@protected("accounting.import_reports")
@require_http_methods(["GET", "POST"])
def import_view(request):
    form = ImportForm(request.POST or None, request.FILES or None, user=request.user, initial={
        "issuer": request.GET.get("issuer"), "period": request.GET.get("period", timezone.localdate().strftime("%Y-%m"))})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            batch, created = import_report(user=request.user, issuer=data["issuer"], period=data["period"], source=data["source"], upload=data["file"])
        except ValidationError as error:
            form.add_error("file", error)
        else:
            messages.success(request, f"Versión {batch.pk}: {batch.document_count} comprobantes, {batch.line_count} líneas." if created
                             else f"Este archivo ya fue importado como versión {batch.pk}; no se duplicó.")
            source_param = "legacy" if batch.source == "OSIPTEL" else "rvie"
            return redirect(scope_url(batch.issuer, batch.period, **{source_param: batch.pk}))
    return render(request, "accounting/import.html", {"form": form}, status=400 if request.method == "POST" else 200)


@protected()
@require_http_methods(["GET", "POST"])
def document_view(request, pk):
    doc = get_object_or_404(Document.objects.select_related("batch__issuer", "batch__imported_by"), pk=pk,
                            batch__issuer__in=available_issuers(request.user))
    form = ReviewForm(request.POST or None, document=doc)
    if request.method == "POST":
        require_access(request.user, doc.batch.issuer, "accounting.review_documents")
        if form.is_valid():
            with transaction.atomic():
                review = Review.objects.create(document=doc, actor=request.user, line_id=form.cleaned_data["line"],
                    note=form.cleaned_data["note"], concept=form.cleaned_data["concept"], technology=form.cleaned_data["technology"])
                AuditEvent.objects.create(actor=request.user, method="POST", route_name="accounting:document", path=request.path,
                    description="Anotó evidencia contable", changes={"document": doc.pk, "review": review.pk})
            messages.success(request, "Observación conservada. Los importes y estados de origen no se modificaron.")
            return redirect("accounting:document", pk=doc.pk)
    return render(request, "accounting/document.html", {"document": doc, "batch": doc.batch, "form": form,
        "flags": [FLAGS.get(flag, flag) for flag in doc.flags], "lines": doc.lines.all(),
        "reviews": doc.reviews.select_related("actor", "line"),
        "back_url": scope_url(doc.batch.issuer, doc.batch.period, **{("legacy" if doc.batch.source == "OSIPTEL" else "rvie"): doc.batch_id})},
        status=400 if request.method == "POST" else 200)


@protected("accounting.manage_access")
@require_http_methods(["GET", "POST"])
def access_view(request):
    form = AccessForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            access, created = CompanyAccess.objects.update_or_create(user=data["user"], issuer=data["issuer"],
                defaults={"enabled": data["enabled"], "updated_by": request.user})
            AuditEvent.objects.create(actor=request.user, method="POST", route_name="accounting:access", path=request.path,
                description="Actualizó acceso contable por empresa", changes={"access": access.pk, "user": data["user"].pk,
                    "issuer": data["issuer"].pk, "enabled": data["enabled"]})
        messages.success(request, "Acceso contable actualizado.")
        return redirect("accounting:access")
    return render(request, "accounting/access.html", {"form": form,
        "accesses": CompanyAccess.objects.select_related("user", "issuer", "updated_by").order_by("user__username", "issuer__business_name")},
        status=400 if request.method == "POST" else 200)


@protected()
@require_http_methods(["GET"])
def rvie_template(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="plantilla_comparacion_RVIE_SICV_v1.csv"'
    response.write("\ufeff")
    csv.writer(response, delimiter=";").writerow(RVIE_HEADERS)
    return response


@protected()
@require_http_methods(["GET"])
def demo_view(request):
    return render(request, "accounting/demo.html")
