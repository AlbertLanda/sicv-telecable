"""Créditos comerciales aprobados; no borran cargos ni producen notas fiscales."""
from decimal import Decimal
import hashlib
import json
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.customers.models import Customer
from apps.organization.models import Branch
from .models import Charge, DebtAdjustment, Payment
from .services import payment_money


def review_branches(user):
    if not user.is_active or not user.has_perm("payments.review_debt_adjustment"):
        return Branch.objects.none()
    if user.is_superuser or user.role == "ADMIN":
        return Branch.objects.all()
    scope = Q(offices__authorized_users=user)
    if user.branch_id:
        scope |= Q(pk=user.branch_id)
    if user.office_id:
        scope |= Q(offices__pk=user.office_id)
    return Branch.objects.filter(scope).distinct()


def scoped_charges(user):
    charges = Charge.objects.select_related("customer", "subscription__address__zone__branch")
    if user.is_active and user.has_perm("payments.request_debt_adjustment") and (user.is_superuser or user.role in ("ATC", "ADMIN")):
        # ATC mantiene consulta/solicitud entre sedes; aprobar exige ámbito propio.
        return charges
    branches = review_branches(user)
    return charges.filter(Q(subscription__address__zone__branch__in=branches)
        | Q(subscription__address__zone__isnull=True, customer__branch__in=branches))


def can_review(user, charge):
    branch_id = charge.customer.branch_id
    if charge.subscription_id and charge.subscription.address.zone_id:
        branch_id = charge.subscription.address.zone.branch_id
    return review_branches(user).filter(pk=branch_id).exists()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def financial_state(charge):
    return {"charge": charge.pk, "amount": str(charge.amount), "status": charge.status,
        "discount": str(charge.early_discount), "deadline": str(charge.discount_deadline),
        "payments": [[a.pk, str(a.amount), str(a.discount)] for a in charge.allocations.filter(payment__status=Payment.Status.REGISTERED).order_by("pk")],
        "adjustments": list(charge.adjustments.filter(status="APPROVED").order_by("pk").values_list("pk", flat=True))}


def balance_snapshot(charge):
    return {"date": str(timezone.localdate()), "original": str(charge.amount),
            "balance": str(charge.balance_on()), "nominal_balance": str(charge.nominal_balance),
            "adjusted": str(charge.adjusted_amount), "state": financial_state(charge)}


def lock_charge(pk):
    customer_id = Charge.objects.values_list("customer_id", flat=True).get(pk=pk)
    Customer.objects.select_for_update().get(pk=customer_id)
    return Charge.objects.select_for_update(of=("self",)).select_related("customer", "subscription__address__zone__branch").get(pk=pk)


@transaction.atomic
def request_adjustment(*, charge_id, actor, amount, reason, reference, request_key, reversal_id=None):
    charge = lock_charge(charge_id)
    if not actor.is_active or not actor.has_perm("payments.request_debt_adjustment"):
        raise PermissionDenied
    if not scoped_charges(actor).filter(pk=charge.pk).exists():
        raise PermissionDenied
    amount = payment_money(amount)
    reason, reference = str(reason or "").strip(), str(reference or "").strip()
    if not reason or len(reason) > 500 or not reference or len(reference) > 120 or amount <= 0:
        raise ValidationError("Indique monto positivo, motivo (hasta 500 caracteres) y referencia de sustento (hasta 120).")
    try:
        key = uuid.UUID(str(request_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Actualice el formulario para generar una nueva solicitud.")
    fingerprint = _digest([charge.pk, actor.pk, str(amount.quantize(Decimal('.01'))), reason, reference, reversal_id])
    prior = DebtAdjustment.objects.filter(request_key=key).first()
    if prior:
        if prior.fingerprint != fingerprint:
            raise ValidationError("La solicitud ya se utilizó con otros datos.")
        return prior
    if charge.status == Charge.Status.CANCELLED:
        raise ValidationError("No se ajusta un cargo anulado.")
    if charge.adjustments.filter(status="PENDING").exists():
        raise ValidationError("Este cargo ya tiene una solicitud pendiente de revisión.")
    original = None
    if reversal_id:
        original = charge.adjustments.filter(pk=reversal_id, status="APPROVED", amount__gt=0).first()
        if not original or original.amount != amount or original.reversals.filter(status__in=["PENDING", "APPROVED"]).exists():
            raise ValidationError("Solo se restituye una vez el importe completo de un ajuste aprobado.")
    elif amount > charge.nominal_balance:
        raise ValidationError("El ajuste supera el saldo sin descuento temporal. No se reduce dinero ya cobrado.")
    try:
        with transaction.atomic():
            return DebtAdjustment.objects.create(charge=charge, amount=-amount if original else amount, reason=reason, reference=reference,
                reversal_of=original, requested_by=actor, request_key=key, fingerprint=fingerprint,
                expected_state=_digest(financial_state(charge)), request_snapshot=balance_snapshot(charge))
    except IntegrityError:
        raise ValidationError("La solicitud ya se registró o el cargo tiene otro ajuste pendiente. Actualice la pantalla.")


@transaction.atomic
def review_adjustment(*, adjustment_id, actor, decision, note):
    charge_id = DebtAdjustment.objects.values_list("charge_id", flat=True).get(pk=adjustment_id)
    charge = lock_charge(charge_id)
    adjustment = DebtAdjustment.objects.select_for_update().get(pk=adjustment_id)
    if not can_review(actor, charge) or actor.pk == adjustment.requested_by_id:
        raise PermissionDenied("La revisión requiere otra persona autorizada para la sede del servicio.")
    note = str(note or "").strip()
    if decision not in ("APPROVED", "REJECTED") or not note or len(note) > 500:
        raise ValidationError("Seleccione aprobar o rechazar e indique un comentario de hasta 500 caracteres.")
    if adjustment.status != "PENDING":
        raise ValidationError("La solicitud ya fue revisada.")
    before = balance_snapshot(charge)
    if decision == "APPROVED":
        if adjustment.expected_state != _digest(financial_state(charge)) or charge.status == Charge.Status.CANCELLED:
            raise ValidationError("El cargo o sus cobros cambiaron. Rechace esta solicitud y prepare otra con el saldo actualizado.")
        if adjustment.amount > charge.nominal_balance:
            raise ValidationError("El ajuste supera el saldo disponible.")
    adjustment.status, adjustment.reviewed_by, adjustment.reviewed_at = decision, actor, timezone.now()
    adjustment.review_note = note
    adjustment.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
    if decision == "APPROVED":
        charge.refresh_status()
    adjustment.result_snapshot = {"before": before, "after": balance_snapshot(charge)}
    adjustment.save(update_fields=["result_snapshot"])
    return adjustment
