from decimal import Decimal
import uuid

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .adjustments import can_review, request_adjustment, review_adjustment, scoped_charges
from .cash_forms import StyledForm
from .models import DebtAdjustment


class AdjustmentForm(StyledForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    amount = forms.DecimalField(label="Importe a reducir o restituir (S/)", max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    reason = forms.CharField(label="Motivo del ajuste", max_length=500, widget=forms.Textarea(attrs={"rows": 2}))
    reference = forms.CharField(label="Sustento / cargo duplicado / autorización comercial", max_length=120)
    reversal_id = forms.IntegerField(label="ID de ajuste a restituir (solo para revertir un ajuste aprobado)", required=False, min_value=1)


class AdjustmentReviewForm(StyledForm):
    adjustment_id = forms.IntegerField(widget=forms.HiddenInput)
    decision = forms.ChoiceField(label="Decisión", choices=[("APPROVED", "Aprobar"), ("REJECTED", "Rechazar")])
    note = forms.CharField(label="Comentario de revisión", max_length=500, widget=forms.Textarea(attrs={"rows": 2}))


def require_workspace(user):
    if not user.has_perm("payments.request_debt_adjustment") and not user.has_perm("payments.review_debt_adjustment"):
        raise PermissionDenied


@never_cache
@login_required
@require_http_methods(["GET"])
def adjustment_workspace(request):
    require_workspace(request.user)
    charges = scoped_charges(request.user)
    query = request.GET.get("q", "").strip()[:80]
    if query:
        from django.db.models import Q
        charges = charges.filter(Q(customer__code__icontains=query) | Q(customer__document_number=query))
    customer_id = request.GET.get("customer", "")
    if customer_id:
        try:
            charges = charges.filter(customer_id=int(customer_id))
        except ValueError:
            charges = charges.none()
    adjustments = DebtAdjustment.objects.filter(charge__in=charges).select_related("charge__customer", "requested_by", "reviewed_by")
    status = request.GET.get("status", "PENDING")
    if status in DebtAdjustment.Status.values:
        adjustments = adjustments.filter(status=status)
    return render(request, "payments/adjustments/workspace.html", {
        "charges": Paginator(charges.order_by("-pk"), 25).get_page(request.GET.get("page")) if query or customer_id else None,
        "adjustments": Paginator(adjustments, 25).get_page(request.GET.get("review_page")), "q": query,
        "customer_filter": customer_id, "status": status, "statuses": DebtAdjustment.Status.choices,
    })


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def adjustment_charge(request, pk):
    require_workspace(request.user)
    charge = get_object_or_404(scoped_charges(request.user), pk=pk)
    form, review_form = AdjustmentForm(), None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "request":
            form = AdjustmentForm(request.POST)
            if form.is_valid():
                try:
                    request_adjustment(charge_id=pk, actor=request.user, **form.cleaned_data)
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "Solicitud guardada. El saldo cambia solo después de la aprobación.")
                    return redirect("payments:adjustment_charge", pk=pk)
        elif action == "review":
            review_form = AdjustmentReviewForm(request.POST)
            if review_form.is_valid():
                get_object_or_404(charge.adjustments, pk=review_form.cleaned_data["adjustment_id"])
                try:
                    review_adjustment(actor=request.user, **review_form.cleaned_data)
                except ValidationError as exc:
                    review_form.add_error(None, exc)
                else:
                    messages.success(request, "Decisión registrada con el saldo anterior y posterior.")
                    return redirect("payments:adjustment_charge", pk=pk)
        else:
            raise PermissionDenied
    pending = charge.adjustments.filter(status="PENDING").first()
    review_allowed = pending and pending.requested_by_id != request.user.pk and can_review(request.user, charge)
    return render(request, "payments/adjustments/charge.html", {
        "charge": charge, "form": form, "pending": pending,
        "can_request": request.user.has_perm("payments.request_debt_adjustment") and not pending,
        "can_review": review_allowed,
        "review_form": review_form or AdjustmentReviewForm(initial={"adjustment_id": pending.pk if pending else None}),
        "adjustments": charge.adjustments.select_related("requested_by", "reviewed_by"),
    })
