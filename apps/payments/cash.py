"""Caja operativa. Toda escritura se serializa por oficina, antes del talonario.

Una caja empieza a controlarse al abrir su primera sesión. No se inventan cajas
para cobros antiguos. Desde esa activación no se permiten cobros con fecha fuera
de la sesión abierta ni cambios de cobros incluidos en cierres enviados.
"""

from decimal import Decimal
import hashlib
import json
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.organization.models import Office
from .models import CashClose, CashEntry, CashEvent, CashSession, Issuer, Payment, ZERO
from .services import payment_money

DENOMINATIONS = ("200.00", "100.00", "50.00", "20.00", "10.00", "5.00", "2.00", "1.00", "0.50", "0.20", "0.10")
MANUAL_KINDS = ("EXPENSE", "DEPOSIT", "INCOME", "GUARANTEE")


def operate_offices(user, branch):
    offices = Office.objects.filter(branch=branch, is_deposit=False, is_active=True, branch__is_active=True)
    if not user.is_active or not user.has_perm("payments.operate_cash"):
        return offices.none()
    if user.is_superuser or user.role == "ADMIN":
        return offices
    return offices.filter(Q(pk=user.office_id) | Q(authorized_users=user)).distinct()


def review_offices(user):
    offices = Office.objects.filter(is_deposit=False)
    if not user.is_active or not user.has_perm("payments.review_cash"):
        return offices.none()
    if user.is_superuser or user.role == "ADMIN":
        return offices
    # Cambiar la sede de la barra no amplía el ámbito de revisión.
    scope = Q(authorized_users=user) | Q(pk=user.office_id)
    if user.branch_id:
        scope |= Q(branch_id=user.branch_id)
    return offices.filter(scope).distinct()


def visible_sessions(user, branch):
    if not user.is_authenticated or not user.is_active or branch is None:
        return CashSession.objects.none()
    own_offices = operate_offices(user, branch)
    scope = Q(office__in=review_offices(user))
    if user.has_perm("payments.operate_cash"):
        scope |= Q(cashier=user, office__in=own_offices)
    return CashSession.objects.filter(office__branch=branch).filter(scope).select_related("office__branch", "cashier")


def require_operator(user, session):
    if (not user.is_active or not user.has_perm("payments.operate_cash")
            or user.pk != session.cashier_id
            or not operate_offices(user, session.office.branch).filter(pk=session.office_id).exists()):
        raise PermissionDenied


def lock_session(pk):
    office_id = CashSession.objects.values_list("office_id", flat=True).get(pk=pk)
    Office.objects.select_for_update().get(pk=office_id)
    return CashSession.objects.select_for_update(of=("self",)).select_related("office__branch", "cashier").get(pk=pk)


def _text(value, label, max_length, required=False):
    value = str(value or "").strip()
    if len(value) > max_length or (required and not value):
        raise ValidationError(f"{label}: indique un valor de hasta {max_length} caracteres.")
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _cash_entry(payment, session, actor, kind="PAYMENT", reason=""):
    receipt = payment.receipt
    issuer = receipt.sequence.issuer
    return CashEntry.objects.create(
        session=session, kind=kind, amount=payment.amount if kind == "PAYMENT" else -payment.amount,
        method=payment.method, payment=payment, actor=actor,
        issuer=issuer, issuer_label=issuer.business_name if issuer else "Sin emisor configurado",
        issuer_ruc=issuer.ruc if issuer else "", reference=receipt.full_number,
        description=reason or f"Cobro {receipt.full_number}",
        occurred_at=(payment.paid_at or payment.received_at) if kind == "PAYMENT" else timezone.now(),
    )


@transaction.atomic
def open_session(*, actor, office, opening_amount, reason=""):
    office = Office.objects.select_for_update(of=("self",)).select_related("branch").get(pk=office.pk)
    session = CashSession(office=office, cashier=actor, business_date=timezone.localdate())
    require_operator(actor, session)
    if not office.branch.is_active:
        raise ValidationError("La sede está inactiva.")
    previous = CashSession.objects.filter(office=office, cashier=actor).first()
    if previous and (previous.status != "APPROVED" or previous.business_date >= session.business_date):
        raise ValidationError("Ya existe una caja de hoy o una caja anterior pendiente de aprobación.")
    opening_amount = payment_money(opening_amount)
    if opening_amount < ZERO or opening_amount > Decimal("9999999999.99"):
        raise ValidationError("El saldo de apertura debe ser mayor o igual a cero.")
    previous_close = previous.closes.first() if previous else None
    reason = _text(reason, "Motivo de apertura", 300,
                   required=previous_close is None or previous_close.declared_cash != opening_amount)
    session.opening_amount, session.opening_reason, session.previous = opening_amount, reason, previous
    session.save()
    # Incorporación explícita de los cobros ya registrados hoy, una sola vez.
    # La apertura representa SOLO el fondo anterior, excluye estos cobros.
    payments = Payment.objects.filter(office=office, received_by=actor, status="REGISTERED").filter(
        Q(paid_at__date=session.business_date) | Q(paid_at__isnull=True, received_at__date=session.business_date))
    for payment in payments.select_related("receipt__sequence__issuer").order_by("pk"):
        if not hasattr(payment, "receipt"):
            raise ValidationError("Hay un cobro de hoy sin comprobante interno. Regularícelo antes de abrir la caja.")
        if not CashEntry.objects.filter(payment=payment, kind="PAYMENT").exists():
            _cash_entry(payment, session, actor)
    CashEvent.objects.create(session=session, action="OPENED", actor=actor, reason=reason)
    return session


def lock_payment_session(*, office, cashier, paid_at):
    """Se llama dentro de la transacción de cobro, ANTES de bloquear el talonario."""
    if office is None:
        return None
    Office.objects.select_for_update().get(pk=office.pk)
    latest = CashSession.objects.filter(office=office, cashier=cashier).first()
    if latest is None:
        return None
    if (latest.status != "OPEN" or timezone.localdate(paid_at) != latest.business_date
            or latest.business_date != timezone.localdate()):
        raise ValidationError("Abra su caja de hoy antes de cobrar. No se puede registrar dinero en una caja cerrada o con otra fecha.")
    return latest


def book_payment(payment, session, actor):
    if session:
        return _cash_entry(payment, session, actor)


def book_void(payment, actor, reason):
    if payment.office_id:
        Office.objects.select_for_update().get(pk=payment.office_id)
    entry = CashEntry.objects.filter(payment=payment, kind="PAYMENT").select_related("session").first()
    if entry is None:
        return
    if entry.session.status != "OPEN":
        raise ValidationError("Este cobro pertenece a una caja enviada o aprobada. Devuelva el cierre a corrección antes de anular; un cierre aprobado no se modifica.")
    CashEntry.objects.create(session=entry.session, kind="VOID", amount=-entry.amount, method=entry.method,
        payment=payment, actor=actor, issuer=entry.issuer, issuer_label=entry.issuer_label,
        issuer_ruc=entry.issuer_ruc, reference=entry.reference, description=reason, occurred_at=timezone.now())


def snapshot_session(session):
    entries, methods, issuers = [], {}, {}
    balance = session.opening_amount
    for entry in session.entries.select_related("actor").order_by("pk"):
        if entry.method == "CASH":
            balance += entry.amount
        methods[entry.method] = methods.get(entry.method, ZERO) + entry.amount
        key = f"{entry.issuer_id or 0}:{entry.issuer_ruc}:{entry.issuer_label}"
        row = issuers.setdefault(key, {"name": entry.issuer_label, "ruc": entry.issuer_ruc, "net": ZERO})
        row["net"] += entry.amount
        entries.append({"id": entry.pk, "kind": entry.get_kind_display(), "amount": str(entry.amount),
                        "method": entry.method, "issuer": entry.issuer_label, "ruc": entry.issuer_ruc,
                        "description": entry.description, "reference": entry.reference, "bank": entry.bank,
                        "account": entry.account, "document_type": entry.document_type, "document_number": entry.document_number,
                        "payment_id": entry.payment_id, "reversal_of": entry.reversal_of_id,
                        "actor": str(entry.actor), "occurred_at": entry.occurred_at.isoformat(), "recorded_at": entry.created_at.isoformat(),
                        "cash_balance": str(balance)})
    for row in issuers.values():
        row["net"] = str(row["net"])
    return {"schema": 1, "session_id": session.pk, "date": str(session.business_date), "currency": "PEN",
            "cashier": str(session.cashier), "cashier_id": session.cashier_id,
            "office": str(session.office), "office_id": session.office_id, "branch": session.office.branch.name,
            "opening": str(session.opening_amount), "opening_reason": session.opening_reason,
            "previous_session_id": session.previous_id, "methods": {key: str(value) for key, value in methods.items()},
            "issuers": list(issuers.values()), "entries": entries,
            "expected_cash": str(session.opening_amount + methods.get("CASH", ZERO))}


@transaction.atomic
def add_movement(*, session_id, actor, request_key, kind, amount, issuer_id, description,
                 reference="", bank="", account="", document_type="", document_number=""):
    session = lock_session(session_id)
    require_operator(actor, session)
    if kind not in MANUAL_KINDS:
        raise ValidationError("Tipo de movimiento no permitido.")
    amount = payment_money(amount)
    if amount <= ZERO:
        raise ValidationError("Indique un importe mayor a cero.")
    try:
        key = uuid.UUID(str(request_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Actualice el formulario antes de registrar el movimiento.")
    try:
        issuer_id = int(issuer_id)
    except (ValueError, TypeError):
        raise ValidationError("Seleccione una empresa habilitada para esta oficina.")
    data = dict(session_id=session.pk, actor_id=actor.pk, kind=kind, amount=str(amount.quantize(Decimal(".01"))), issuer_id=issuer_id,
                description=_text(description, "Motivo", 300, True),
                reference=_text(reference, "Operación o referencia", 100, kind == "DEPOSIT"),
                bank=_text(bank, "Banco", 100, kind == "DEPOSIT"),
                account=_text(account, "Cuenta de destino", 100, kind == "DEPOSIT"),
                document_type=_text(document_type, "Tipo de sustento", 50, kind == "EXPENSE"),
                document_number=_text(document_number, "Número de sustento", 100, kind == "EXPENSE"))
    fingerprint = _digest(data)
    existing = CashEntry.objects.filter(request_key=key).first()
    if existing:
        if existing.fingerprint != fingerprint:
            raise ValidationError("La solicitud ya se registró con otros datos; abra un formulario nuevo.")
        return existing
    if session.status != "OPEN":
        raise ValidationError("La caja está enviada o aprobada y no admite movimientos.")
    # Solo empresas con talonario habilitado en esta oficina.
    issuer = Issuer.objects.filter(pk=issuer_id, is_active=True, sequences__offices=session.office, sequences__is_active=True).distinct().first()
    if issuer is None:
        raise ValidationError("Seleccione una empresa habilitada para esta oficina.")
    deposit_key = None
    if kind == "DEPOSIT":
        deposit_key = _digest([issuer.pk, str(session.business_date), *(data[k].upper().replace(" ", "") for k in ("bank", "account", "reference"))])
    data["amount"] = -amount if kind in ("EXPENSE", "DEPOSIT") else amount
    try:
        with transaction.atomic():
            entry = CashEntry.objects.create(**data, method="CASH", issuer_label=issuer.business_name, issuer_ruc=issuer.ruc,
                                            request_key=key, fingerprint=fingerprint, deposit_key=deposit_key,
                                            occurred_at=timezone.now())
    except IntegrityError:
        raise ValidationError("Esta solicitud o depósito ya fue registrado. Revise los movimientos antes de repetirlo.")
    CashEvent.objects.create(session=session, action="MOVEMENT", actor=actor, reason=f"Movimiento #{entry.pk}")
    return entry


@transaction.atomic
def reverse_movement(*, session_id, entry_id, actor, reason):
    session = lock_session(session_id)
    require_operator(actor, session)
    reason = _text(reason, "Motivo de reversión", 300, True)
    original = CashEntry.objects.filter(pk=entry_id, session__cashier=actor, session__office=session.office,
                                        kind__in=MANUAL_KINDS).select_related("session").first()
    if original is None:
        raise ValidationError("Seleccione un movimiento propio de esta oficina; los cobros se anulan desde su comprobante.")
    if session.status != "OPEN" or (original.session_id != session.pk and original.session.status != "APPROVED"):
        raise ValidationError("La corrección requiere una caja abierta y un movimiento de ella o de un cierre aprobado anterior.")
    if CashEntry.objects.filter(reversal_of=original).exists():
        raise ValidationError("El movimiento ya fue revertido.")
    if original.bank_matches.filter(active=True).exists():
        raise ValidationError("Contabilidad debe deshacer la conciliación bancaria antes de revertir el depósito.")
    entry = CashEntry.objects.create(session=session, kind="REVERSAL", amount=-original.amount, method=original.method,
        issuer=original.issuer, issuer_label=original.issuer_label, issuer_ruc=original.issuer_ruc, actor=actor,
        description=reason, reference=f"Corrección movimiento #{original.pk}", reversal_of=original, occurred_at=timezone.now())
    CashEvent.objects.create(session=session, action="REVERSED", actor=actor, reason=f"Movimiento #{original.pk}; reversión #{entry.pk}: {reason}"[:500])
    return entry


@transaction.atomic
def submit_close(*, session_id, actor, counts, explanation=""):
    session = lock_session(session_id)
    require_operator(actor, session)
    if session.status != "OPEN":
        raise ValidationError("La caja ya se envió o fue aprobada.")
    if set(counts) != set(DENOMINATIONS):
        raise ValidationError("Complete el arqueo por denominaciones.")
    normalized = {}
    for denomination, count in counts.items():
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 1000000:
            raise ValidationError("El arqueo admite cantidades enteras de 0 a 1000000.")
        normalized[denomination] = count
    declared = sum((Decimal(value) * count for value, count in normalized.items()), ZERO)
    snapshot = snapshot_session(session)
    expected = Decimal(snapshot["expected_cash"])
    difference = declared - expected
    explanation = _text(explanation, "Explicación de diferencia", 500, difference != ZERO)
    snapshot.update(counts=normalized, declared_cash=str(declared), difference=str(difference), explanation=explanation)
    revision = (session.closes.first().revision + 1) if session.closes.exists() else 1
    close = CashClose.objects.create(session=session, revision=revision, submitted_by=actor,
        expected_cash=expected, declared_cash=declared, difference=difference, explanation=explanation,
        snapshot=snapshot, digest=_digest(snapshot))
    session.status = "SUBMITTED"
    session.save(update_fields=["status"])
    CashEvent.objects.create(session=session, close=close, action="SUBMITTED", actor=actor, reason=explanation)
    return close


@transaction.atomic
def review_close(*, session_id, close_id, actor, decision, reason):
    session = lock_session(session_id)
    if not review_offices(actor).filter(pk=session.office_id).exists() or actor.pk == session.cashier_id:
        raise PermissionDenied("La revisión corresponde a otra persona autorizada.")
    reason = _text(reason, "Comentario de revisión", 500, True)
    latest = session.closes.first()
    if session.status != "SUBMITTED" or latest is None or latest.pk != close_id:
        raise ValidationError("El cierre cambió o ya fue revisado. Actualice la pantalla.")
    if decision not in ("APPROVED", "RETURNED"):
        raise ValidationError("Decisión no válida.")
    if latest.digest != _digest(latest.snapshot):
        raise ValidationError("La evidencia del cierre no coincide con su huella guardada.")
    CashEvent.objects.create(session=session, close=latest, action=decision, actor=actor, reason=reason)
    session.status = "APPROVED" if decision == "APPROVED" else "OPEN"
    session.save(update_fields=["status"])
    return session
