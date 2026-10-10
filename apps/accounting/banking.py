"""Evidencia bancaria local: importar no registra dinero ni cancela deuda."""
import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
from io import StringIO
import json
import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.customers.models import Customer
from apps.organization.models import Office
from apps.payments.models import CashEntry, Issuer, Payment
from .access import available_issuers, require_access
from .models import BankAccount, BankEvent, BankLine, BankMatch, BankStatement

HEADERS = ["id_movimiento", "fecha", "operacion", "descripcion", "moneda", "ingreso", "salida", "cuenta"]
MAX_BYTES, MAX_ROWS = 2 * 1024 * 1024, 10000


def accounts_for(user):
    if not user.has_perm("accounting.view_bank"):
        return BankAccount.objects.none()
    return BankAccount.objects.filter(issuer__in=available_issuers(user)).select_related("issuer")


def check_access(actor, account, permission="accounting.view_bank"):
    require_access(actor, account.issuer, permission)


def account_number(value):
    value = re.sub(r"[\s-]", "", str(value)).upper()
    if not re.fullmatch(r"[A-Z0-9]{4,40}", value, flags=re.ASCII):
        raise ValidationError("Indique la cuenta completa (4 a 40 caracteres); se conservan los ceros iniciales.")
    return value


def operation_key(value):
    return re.sub(r"\s+", "", str(value)).upper()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def note_text(value):
    value = str(value or "").strip()
    if not value or len(value) > 500:
        raise ValidationError("Indique un comentario de 1 a 500 caracteres.")
    return value


@transaction.atomic
def create_account(*, actor, issuer_id, bank, number, label):
    issuer = Issuer.objects.select_for_update().get(pk=issuer_id)
    require_access(actor, issuer, "accounting.manage_bank_accounts")
    bank, label = " ".join(str(bank).upper().split()), str(label).strip()
    if not bank or len(bank) > 80 or not label or len(label) > 120:
        raise ValidationError("Indique banco y nombre de cuenta válidos.")
    try:
        with transaction.atomic():
            account = BankAccount.objects.create(issuer=issuer, bank=bank, number=account_number(number), label=label, created_by=actor)
    except IntegrityError:
        raise ValidationError("La cuenta ya existe. Verifique banco, cuenta y empresa antes de continuar.")
    BankEvent.objects.create(account=account, actor=actor, action="Cuenta creada", note="Cuenta PEN configurada explícitamente.")
    return account


def parse_statement(raw, account):
    if not raw or len(raw) > MAX_BYTES:
        raise ValidationError("El CSV debe contener datos y ocupar como máximo 2 MB.")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError("Guarde el extracto normalizado como CSV UTF-8.")
    if "\x00" in content:
        raise ValidationError("El archivo contiene caracteres no válidos.")
    if not content.strip():
        raise ValidationError("El CSV no contiene movimientos.")
    first = content.splitlines()[0]
    delimiter = ";" if first.split(";") == HEADERS else ","
    rows = csv.reader(StringIO(content), delimiter=delimiter, strict=True)
    parsed, seen = [], set()
    try:
        if next(rows) != HEADERS:
            raise ValidationError("La cabecera no coincide con la plantilla bancaria. No se deducen columnas ni monedas.")
        for index, row in enumerate(rows, 2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(parsed) >= MAX_ROWS or len(row) != len(HEADERS):
                raise ValidationError(f"Fila {index}: límite de 10000 movimientos o número de columnas incorrecto.")
            cells = dict(zip(HEADERS, [value.strip() for value in row]))
            external, operation = cells["id_movimiento"], cells["operacion"]
            if not external or len(external) > 120 or not operation or len(operation) > 120 or len(cells["descripcion"]) > 500:
                raise ValidationError(f"Fila {index}: ID/operación requeridos (máximo 120) y descripción de hasta 500 caracteres.")
            if external in seen:
                raise ValidationError(f"Fila {index}: ID de movimiento repetido dentro del archivo.")
            seen.add(external)
            if cells["moneda"] != account.currency or account_number(cells["cuenta"]) != account.number:
                raise ValidationError(f"Fila {index}: cuenta o moneda diferente a la seleccionada.")
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells["fecha"], flags=re.ASCII):
                    raise ValueError
                day = date.fromisoformat(cells["fecha"])
                if not date(2000, 1, 1) <= day <= timezone.localdate():
                    raise ValueError
                amounts = []
                for key in ("ingreso", "salida"):
                    text = cells[key] or "0"
                    if not re.fullmatch(r"\d{1,12}(\.\d{1,2})?", text, flags=re.ASCII):
                        raise ValueError
                    amounts.append(Decimal(text))
                income, expense = amounts
                if (income > 0) == (expense > 0):
                    raise ValueError
            except (ValueError, InvalidOperation):
                raise ValidationError(f"Fila {index}: fecha ISO válida hasta hoy e importe positivo en ingreso o salida; use punto decimal sin miles.")
            item = {"external_id": external, "date": day, "operation": operation,
                    "operation_key": operation_key(operation), "description": cells["descripcion"], "amount": (income - expense).quantize(Decimal(".01"))}
            item["fingerprint"] = digest({key: str(value) for key, value in item.items()})
            parsed.append(item)
    except (csv.Error, StopIteration):
        raise ValidationError("El CSV no está completo o sus comillas no son válidas.")
    if not parsed:
        raise ValidationError("El CSV no contiene movimientos.")
    return parsed


@transaction.atomic
def import_statement(*, actor, account_id, filename, raw):
    account = BankAccount.objects.select_for_update(of=("self",)).select_related("issuer").get(pk=account_id)
    check_access(actor, account, "accounting.import_bank")
    parsed = parse_statement(raw, account)
    sha = hashlib.sha256(raw).hexdigest()
    previous = account.statements.filter(sha256=sha).first()
    if previous:
        return previous
    # Bloqueo de cuenta serializa archivos solapados; un ID cambiado rechaza todo.
    existing = {}
    keys = [row["external_id"] for row in parsed]
    for start in range(0, len(keys), 400):
        existing.update({line.external_id: line for line in account.lines.filter(external_id__in=keys[start:start + 400])})
    new, linked = [], []
    for row in parsed:
        prior = existing.get(row["external_id"])
        if prior:
            if prior.fingerprint != row["fingerprint"]:
                raise ValidationError(f"El ID {prior.external_id} ya existe con otros datos. Revise el extracto; no se reemplaza evidencia.")
            linked.append(prior)
        else:
            new.append(BankLine(account=account, **row))
    BankLine.objects.bulk_create(new)
    linked.extend(new)
    batch = BankStatement.objects.create(account=account, filename=str(filename).replace("\\", "/").split("/")[-1][:180],
        sha256=sha, original=raw, imported_by=actor, row_count=len(parsed), new_count=len(new))
    batch.lines.add(*linked)
    BankEvent.objects.create(account=account, actor=actor, action="Extracto importado", note=f"Extracto #{batch.pk}: {len(new)} nuevos / {len(parsed)} filas; SHA-256 {sha}")
    return batch


def payment_issuer(payment):
    original = CashEntry.objects.filter(payment=payment, kind="PAYMENT").first()
    return original.issuer_id if original else payment.receipt.sequence.issuer_id


def payment_candidates(line):
    # La cuenta aún no está acreditada en pagos antiguos: siempre confirmar.
    start, end = line.date - timedelta(days=3), line.date + timedelta(days=3)
    payments = Payment.objects.filter(status="REGISTERED", amount=line.amount,
        paid_at__date__range=(start, end)).exclude(method="CASH").filter(
        Q(cashentry__kind="PAYMENT", cashentry__issuer=line.account.issuer)
        | Q(cashentry__isnull=True, receipt__sequence__issuer=line.account.issuer)
    ).exclude(bank_matches__active=True).select_related("receipt__sequence", "customer").distinct()
    return [payment for payment in payments.iterator(chunk_size=200) if operation_key(payment.reference) == line.operation_key]


def deposit_candidates(line):
    start, end = line.date - timedelta(days=3), line.date + timedelta(days=3)
    entries = CashEntry.objects.filter(kind="DEPOSIT", issuer=line.account.issuer, amount=-line.amount,
        session__business_date__range=(start, end), reversal__isnull=True).exclude(bank_matches__active=True)
    return [entry for entry in entries.iterator(chunk_size=200) if operation_key(entry.reference) == line.operation_key
        and " ".join(entry.bank.upper().split()) == line.account.bank
        and re.sub(r"[\s-]", "", entry.account).upper() == line.account.number]


@transaction.atomic
def confirm_match(*, actor, line_id, kind, target_id, note):
    # Orden de bloqueo compatible con cobranza/caja: cliente u oficina, cuenta.
    line = BankLine.objects.select_related("account__issuer").get(pk=line_id)
    check_access(actor, line.account, "accounting.reconcile_bank")
    note = note_text(note)
    payment, entry = None, None
    if kind == "PAYMENT":
        customer_id = Payment.objects.values_list("customer_id", flat=True).get(pk=target_id)
        Customer.objects.select_for_update().get(pk=customer_id)
        payment = Payment.objects.select_for_update(of=("self",)).select_related("receipt__sequence", "customer").get(pk=target_id)
    elif kind == "DEPOSIT":
        office_id = CashEntry.objects.values_list("session__office_id", flat=True).get(pk=target_id)
        Office.objects.select_for_update().get(pk=office_id)
        entry = CashEntry.objects.select_for_update().get(pk=target_id)
    else:
        raise ValidationError("Seleccione un cobro o depósito de caja.")
    BankAccount.objects.select_for_update().get(pk=line.account_id)
    line = BankLine.objects.select_for_update().get(pk=line.pk)
    if line.amount <= 0 or line.matches.filter(active=True).exists():
        raise ValidationError("Solo se vincula un ingreso bancario pendiente; la salida se mantiene para revisión.")
    if payment:
        if (payment.status != "REGISTERED" or payment.method == "CASH" or payment.amount != line.amount
                or not hasattr(payment, "receipt") or payment_issuer(payment) != line.account.issuer_id):
            raise ValidationError("El cobro debe estar vigente, ser no efectivo y coincidir exactamente en empresa e importe PEN.")
        if payment.bank_matches.filter(active=True).exists():
            raise ValidationError("El cobro ya tiene una conciliación activa.")
        target = {"kind": "Cobro", "id": payment.pk, "amount": str(payment.amount), "reference": payment.reference,
                  "date": str(timezone.localdate(payment.paid_at or payment.received_at)),
                  "receipt": payment.receipt.full_number, "customer": payment.customer.code}
    else:
        if (entry.kind != "DEPOSIT" or entry.issuer_id != line.account.issuer_id or -entry.amount != line.amount
                or CashEntry.objects.filter(reversal_of=entry).exists()
                or " ".join(entry.bank.upper().split()) != line.account.bank
                or account_number(entry.account) != line.account.number):
            raise ValidationError("El depósito debe coincidir en empresa, banco, cuenta e importe y no estar revertido.")
        if entry.bank_matches.filter(active=True).exists():
            raise ValidationError("El depósito ya tiene una conciliación activa.")
        target = {"kind": "Depósito de caja", "id": entry.pk, "amount": str(-entry.amount), "reference": entry.reference,
                  "date": str(entry.session.business_date), "receipt": "", "customer": ""}
    snapshot = {"bank": line.account.bank, "account": line.account.number, "issuer_id": line.account.issuer_id,
                "currency": line.account.currency, "line": {"id": line.pk, "external_id": line.external_id, "date": str(line.date),
                "operation": line.operation, "amount": str(line.amount), "fingerprint": line.fingerprint}, "target": target}
    match = BankMatch.objects.create(line=line, payment=payment, cash_entry=entry, confirmed_by=actor, note=note, snapshot=snapshot)
    BankEvent.objects.create(account=line.account, line=line, actor=actor, action="Conciliación confirmada", note=f"Vínculo #{match.pk}: {note}"[:500])
    return match


@transaction.atomic
def release_match(*, actor, match_id, reason):
    match = BankMatch.objects.select_related("line__account__issuer").get(pk=match_id)
    check_access(actor, match.line.account, "accounting.reconcile_bank")
    BankAccount.objects.select_for_update().get(pk=match.line.account_id)
    match = BankMatch.objects.select_for_update().get(pk=match_id)
    if not match.active:
        raise ValidationError("La conciliación ya fue deshecha.")
    match.active, match.released_by, match.released_at, match.release_reason = False, actor, timezone.now(), note_text(reason)
    match.save(update_fields=["active", "released_by", "released_at", "release_reason"])
    BankEvent.objects.create(account=match.line.account, line=match.line, actor=actor, action="Conciliación deshecha", note=f"Vínculo #{match.pk}: {match.release_reason}"[:500])
    return match


def annotate_line(*, actor, line_id, note):
    line = BankLine.objects.select_related("account__issuer").get(pk=line_id)
    check_access(actor, line.account, "accounting.reconcile_bank")
    return BankEvent.objects.create(account=line.account, line=line, actor=actor, action="Observación", note=note_text(note))
