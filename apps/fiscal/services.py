"""Operaciones de preparación; ninguna hace llamadas a SUNAT/proveedores."""

from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.customers.models import Customer
from apps.payments.models import Charge, Issuer
from .models import DocumentType, FiscalDocument, FiscalEvent, FiscalProfile, FiscalProfileRevision


PROFILE_FIELDS = (
    "modality", "provider_name", "document_types", "billing_trigger",
    "tax_rules_confirmed", "receiver_rules_confirmed", "confirmation_reference",
)


def profile_snapshot(profile):
    return {name: getattr(profile, name) for name in PROFILE_FIELDS}


@transaction.atomic
def save_profile(*, actor, issuer_id, values):
    _require(actor, "fiscal.add_fiscalprofile")
    _require(actor, "fiscal.change_fiscalprofile")
    issuer = Issuer.objects.select_for_update().get(pk=issuer_id, is_active=True)
    profile = FiscalProfile.objects.filter(issuer=issuer).first() or FiscalProfile(issuer=issuer)
    for name in PROFILE_FIELDS:
        if name in values:
            setattr(profile, name, values[name])
    profile.updated_by = actor
    profile.full_clean()
    profile.save()
    FiscalProfileRevision.objects.create(profile=profile, actor=actor, snapshot=profile_snapshot(profile))
    return profile


def _require(actor, permission):
    if not actor.is_authenticated or not actor.is_active or not actor.has_perm(permission):
        raise PermissionDenied


@transaction.atomic
def prepare_draft(*, actor, branch, customer_id, issuer_id, document_type,
                  charge_ids, proposed_issue_date, request_key):
    _require(actor, "fiscal.add_fiscaldocument")
    _require(actor, "fiscal.view_fiscaldocument")
    if branch is None:
        raise ValidationError("Seleccione una sede activa.")
    try:
        key = uuid.UUID(str(request_key))
        ids = sorted(int(value) for value in charge_ids)
        customer_id, issuer_id = int(customer_id), int(issuer_id)
    except (TypeError, ValueError, AttributeError):
        raise ValidationError("La solicitud de preparación no es válida.")
    if not ids or len(ids) != len(set(ids)):
        raise ValidationError("Seleccione al menos un cargo, sin repetir.")
    if (document_type not in DocumentType.values or not isinstance(proposed_issue_date, date)
            or isinstance(proposed_issue_date, datetime)):
        raise ValidationError("Indique tipo de documento y fecha válidos.")

    request = dict(customer=customer_id, issuer=issuer_id, branch=branch.pk,
                   document_type=document_type, charges=ids,
                   date=proposed_issue_date.isoformat(), actor=actor.pk)
    fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    # Un orden común de bloqueo serializa la preparación del mismo abonado.
    # SQLite no acredita concurrencia; producción usa PostgreSQL.
    customer = Customer.objects.select_for_update().filter(pk=customer_id, branch=branch).first()
    if customer is None:
        raise ValidationError("El abonado no pertenece a la sede activa.")
    existing = FiscalDocument.objects.filter(request_key=key).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise ValidationError("La solicitud ya se utilizó con otros datos. Abra un nuevo formulario.")
        return existing
    issuer = Issuer.objects.filter(pk=issuer_id, is_active=True).first()
    if issuer is None:
        raise ValidationError("Seleccione una empresa emisora activa.")
    charges = list(Charge.objects.select_for_update().filter(pk__in=ids, customer=customer).order_by("pk"))
    if len(charges) != len(ids) or any(c.status == Charge.Status.CANCELLED for c in charges):
        raise ValidationError("Hay cargos ajenos al abonado, inexistentes o anulados.")
    currencies = {charge.currency for charge in charges}
    if len(currencies) != 1:
        raise ValidationError("Un borrador no puede mezclar monedas.")
    if any(charge.amount <= 0 for charge in charges):
        raise ValidationError("Los cargos deben tener importes positivos.")

    profile = FiscalProfile.objects.filter(issuer=issuer).first()
    decisions = profile.pending_decisions if profile else ["Configuración fiscal de la empresa"]
    if profile and document_type not in profile.document_types:
        decisions = [*decisions, "Uso de este tipo de documento por la empresa"]
    snapshot = {
        "version": 1,
        "issuer": {"id": issuer.pk, "business_name": issuer.business_name, "ruc": issuer.ruc, "address": issuer.address},
        "receiver_candidate": {"customer_id": customer.pk, "code": customer.code, "name": str(customer),
                               "document_type": customer.document_type, "document_number": customer.document_number},
        "profile": profile_snapshot(profile) if profile else {},
        "pending_decisions": decisions,
        "lines": [{"charge_id": c.pk, "description": c.description, "concept": c.concept,
                   "quantity": str(c.quantity), "source_amount": str(c.amount),
                   "period": c.period.isoformat() if c.period else "",
                   "period_end": c.period_end.isoformat() if c.period_end else "",
                   "early_discount": str(c.early_discount),
                   "discount_deadline": c.discount_deadline.isoformat() if c.discount_deadline else ""}
                  for c in charges],
        "limitations": ["Receptor fiscal por validar para esta operación",
                        "Impuestos y descuentos fiscales sin calcular",
                        "Importes originales de cargos; no representan saldo ni dinero cobrado",
                        "Sin XML firmado, correlativo oficial ni respuesta fiscal"],
    }
    document = FiscalDocument(
        request_key=key, request_fingerprint=fingerprint, issuer=issuer, customer=customer, branch=branch,
        document_type=document_type, proposed_issue_date=proposed_issue_date, currency=currencies.pop(),
        source_total=sum((charge.amount for charge in charges), Decimal("0.00")),
        snapshot=snapshot, created_by=actor,
    )
    document.save()
    FiscalEvent.objects.create(document=document, action="CREATED", actor=actor)
    return document


@transaction.atomic
def cancel_draft(*, document_id, actor, branch, reason):
    _require(actor, "fiscal.cancel_fiscaldocument")
    _require(actor, "fiscal.view_fiscaldocument")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Indique el motivo para descartar el borrador.")
    document = FiscalDocument.objects.select_for_update().filter(pk=document_id, branch=branch).first()
    if document is None:
        raise ValidationError("El borrador no pertenece a la sede activa.")
    if document.status == FiscalDocument.Status.CANCELLED:
        return document
    document.status = FiscalDocument.Status.CANCELLED
    document.cancelled_by = actor
    document.cancelled_at = timezone.now()
    document.cancel_reason = reason
    document.save(update_fields=["status", "cancelled_by", "cancelled_at", "cancel_reason"])
    FiscalEvent.objects.create(document=document, action="CANCELLED", actor=actor, reason=reason)
    return document


def submit_document(*, document, actor):
    # Bloqueo de servicio, no solo un botón oculto. Ninguna configuración
    # contable de esta entrega puede habilitar transporte o numeración.
    raise ValidationError(
        "Emisión real no habilitada. Falta implementar y validar el adaptador fiscal, "
        "los cálculos, las series oficiales y la recepción de respuestas."
    )
