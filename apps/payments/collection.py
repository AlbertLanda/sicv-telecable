"""Cobranza actual y transiciones recuperables, sin acciones fiscales."""

from decimal import Decimal
import hashlib
import json
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.customers.models import Customer
from apps.organization.context_processors import available_offices_for_user
from apps.organization.models import Office
from .models import Charge, Payment, PaymentOperationEvent, PaymentSubmission
from .services import discount_for, payment_money, register_payment


def manageable_payments(user, branch):
    """Modificar exige sede de cobro activa y oficina autorizada.

    Administración puede resolver registros antiguos sin oficina. También se
    mantienen las transiciones en sedes que aún no usan oficinas activas.
    """
    if branch is None:
        return Payment.objects.none()
    query = Q(office__in=available_offices_for_user(user, branch))
    if (user.is_superuser or getattr(user, "role", None) == "ADMIN"
            or not Office.objects.filter(branch=branch, is_active=True).exists()):
        query |= Q(office__isnull=True)
    return Payment.objects.filter(branch=branch).filter(query)


def _canonical(value):
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01")), "f")
    if hasattr(value, "pk"):
        return value.pk
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


@transaction.atomic
def collect_payment(*, request_key, expected_total, selected_charge_ids=None, **values):
    """Entrada del flujo web actual: mensualidad completa y clave de solicitud."""
    expected_total = payment_money(expected_total)
    values["amount"] = payment_money(values["amount"])
    if values.get("allocations") is not None:
        values["allocations"] = [(charge, payment_money(value)) for charge, value in values["allocations"]]
    user, customer = values["user"], values["customer"]
    if not user.is_active or not user.has_perm("payments.add_payment"):
        raise PermissionDenied
    try:
        key = uuid.UUID(str(request_key))
        selected = sorted(int(value) for value in (selected_charge_ids or []))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Abra nuevamente la pantalla de cobro: la solicitud no es válida.")
    if len(selected) != len(set(selected)):
        raise ValidationError("No repita un cargo en la selección.")
    payload = {name: _canonical(value) for name, value in values.items()}
    if values.get("allocations"):
        payload["allocations"] = sorted(payload["allocations"], key=lambda pair: pair[0])
    payload["selected_charges"] = selected
    payload["expected_total"] = _canonical(expected_total)
    payload["full_monthly_only"] = True
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    Customer.objects.select_for_update().get(pk=customer.pk)
    existing = PaymentSubmission.objects.select_related("payment__receipt").filter(key=key).first()
    if existing:
        if existing.fingerprint != fingerprint:
            raise ValidationError("Esta solicitud ya se utilizó con otros datos. Abra un nuevo cobro.")
        return existing.payment, existing.payment.receipt

    branch, office = values["branch"], values.get("office")
    if branch is None:
        raise ValidationError("Seleccione una sede activa.")
    if office and not available_offices_for_user(user, branch).filter(pk=office.pk).exists():
        raise PermissionDenied
    if office is None and Office.objects.filter(branch=branch, is_active=True).exists():
        raise ValidationError("Seleccione una oficina autorizada antes de cobrar.")

    intended_ids = selected or [c.pk for c, _ in (values.get("allocations") or [])]
    expected_charges = Charge.objects.filter(customer=customer)
    expected_charges = expected_charges.filter(pk__in=intended_ids) if intended_ids else expected_charges.outstanding()
    current_total = sum((c.balance_on(values.get("day")) for c in expected_charges), Decimal("0.00"))
    if expected_total != current_total:
        raise ValidationError("La deuda cambió desde que abrió la pantalla. Actualice el tablero antes de cobrar.")

    if values.get("allocations") is None and selected:
        charges = list(Charge.objects.select_for_update().filter(customer=customer, pk__in=selected).order_by("pk"))
        if len(charges) != len(selected) or any(c.status == Charge.Status.CANCELLED or c.balance_on(values.get("day")) <= 0 for c in charges):
            raise ValidationError("Alguna deuda seleccionada cambió o ya fue cobrada. Actualice el tablero.")
        values["allocations"] = [(c, c.balance_on(values.get("day"))) for c in charges]
    elif selected:
        if not Charge.objects.filter(customer=customer, pk__in=selected).count() == len(selected):
            raise ValidationError("La selección contiene cargos ajenos al abonado.")
        if {c.pk for c, _ in values["allocations"]} != set(selected):
            raise ValidationError("El reparto debe corresponder a los cargos seleccionados.")
    values["full_monthly_only"] = True
    payment, receipt = register_payment(**values)
    PaymentSubmission.objects.create(key=key, fingerprint=fingerprint, payment=payment)
    return payment, receipt


def _lock_payment(payment_id):
    customer_id = Payment.objects.values_list("customer_id", flat=True).get(pk=payment_id)
    Customer.objects.select_for_update().get(pk=customer_id)
    return Payment.objects.select_for_update().get(pk=payment_id)


@transaction.atomic
def confirm_payment(*, payment_id, paid_at=None, actor=None):
    payment = _lock_payment(payment_id)
    if payment.status != Payment.Status.PENDING:
        raise ValidationError("Solo un pago pendiente se puede confirmar.")
    timestamp = paid_at or timezone.now()
    from .cash import lock_payment_session, book_payment
    cash_session = lock_payment_session(office=payment.office, cashier=payment.received_by, paid_at=timestamp)
    day = timezone.localtime(timestamp).date()
    allocations = list(payment.allocations.order_by("charge_id"))
    charges = {c.pk: c for c in Charge.objects.select_for_update().filter(
        pk__in=[a.charge_id for a in allocations],
    ).order_by("pk")}
    for allocation in allocations:
        charge = charges[allocation.charge_id]
        balance = charge.balance_on(day)
        if charge.status == Charge.Status.CANCELLED or allocation.amount > balance:
            raise ValidationError("El saldo cambió después de registrar el pendiente. Revise el cobro antes de confirmarlo.")
        if payment.full_monthly_only and charge.concept == Charge.Concept.MONTHLY:
            if allocation.amount != balance or allocation.discount != discount_for(charge, allocation.amount, day):
                raise ValidationError("El importe o descuento de la mensualidad cambió. Prepare un nuevo cobro completo.")
    payment.status = Payment.Status.REGISTERED
    payment.paid_at = timestamp
    payment.save(update_fields=["status", "paid_at", "updated_at"])
    book_payment(payment, cash_session, actor or payment.received_by)
    for charge in charges.values():
        charge.refresh_status(day)
    PaymentOperationEvent.objects.create(payment=payment, action="CONFIRMED", actor=actor)
    return payment


@transaction.atomic
def void_payment(*, payment_id, actor, reason):
    reason = (reason or "").strip()
    if not reason or len(reason) > 200:
        raise ValidationError("Indique un motivo de anulación de hasta 200 caracteres.")
    payment = _lock_payment(payment_id)
    if payment.status == Payment.Status.VOIDED:
        raise ValidationError("El pago ya está anulado.")
    if payment.bank_matches.filter(active=True).exists():
        raise ValidationError("Contabilidad debe deshacer la conciliación bancaria antes de anular este cobro.")
    from .cash import book_void
    book_void(payment, actor, reason)
    charges = list(Charge.objects.select_for_update().filter(
        pk__in=payment.allocations.values_list("charge_id", flat=True),
    ).order_by("pk"))
    payment.status = Payment.Status.VOIDED
    payment.voided_at = timezone.now()
    payment.voided_by = actor
    payment.void_reason = reason
    payment.save(update_fields=["status", "voided_at", "voided_by", "void_reason", "updated_at"])
    for charge in charges:
        charge.refresh_status()
    PaymentOperationEvent.objects.create(payment=payment, action="VOIDED", actor=actor, reason=reason)
    return payment
