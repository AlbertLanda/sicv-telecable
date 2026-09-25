"""
Deudas propuestas por una orden de trabajo antes de convertirse en un cargo.

El primer caso es TRASLADO. La propuesta conserva la decisión pendiente sin
mover el saldo del abonado. Aceptarla emite el cargo; descartarla deja motivo,
usuario y fecha para auditoría.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.work_orders.models import TransferDetail

from .models import ChargeConcept, ProposedCharge
from .services import create_manual_charge


TRANSFER_ORDER_TYPE_CODE = "TRANSFER"
TRANSFER_CONCEPT_CODE = "traslado"


def is_transfer_order(work_order):
    """Un traslado es un tipo de OT propio, no un motivo de REQUERIMIENTO."""
    return (
        work_order.order_type_id is not None
        and work_order.order_type.code == TRANSFER_ORDER_TYPE_CODE
    )


def transfer_concept():
    """Concepto obligatorio del catálogo de cobranza."""
    concept = ChargeConcept.objects.filter(
        code=TRANSFER_CONCEPT_CODE,
        is_active=True,
    ).first()

    if concept is None:
        raise ValidationError(
            "No existe el concepto activo «TRASLADO» en el catálogo de cobranza."
        )

    return concept


def transfer_description(work_order):
    subtype = getattr(work_order, "subtype", None)
    if subtype is not None and subtype.code == "INTERNAL":
        return "TRASLADO INTERNO"
    if subtype is not None and subtype.code == "EXTERNAL":
        return "TRASLADO EXTERNO"
    return "TRASLADO"


@transaction.atomic
def propose_transfer_charge(*, work_order):
    """Crea una sola propuesta para una OT de traslado, sin emitir deuda."""
    if not is_transfer_order(work_order):
        return None

    if work_order.subscription_id is None:
        raise ValidationError(
            "Una OT de traslado debe pertenecer a una suscripción."
        )

    concept = transfer_concept()

    existing = ProposedCharge.objects.filter(
        work_order=work_order,
        concept_item=concept,
    ).first()
    if existing is not None:
        return existing

    proposal = ProposedCharge(
        customer_id=work_order.subscription.customer_id,
        subscription=work_order.subscription,
        work_order=work_order,
        concept=concept.family,
        concept_item=concept,
        description=transfer_description(work_order),
    )
    proposal.full_clean()
    proposal.save()
    return proposal


def pending_proposals(customer):
    return (
        ProposedCharge.objects
        .filter(customer=customer, status=ProposedCharge.Status.PENDING)
        .select_related("work_order", "work_order__subtype", "concept_item")
        .order_by("-created_at", "-pk")
    )


def suggested_proposed_charge_amount(proposal):
    """Monto sugerido por la política registrada en la OT de traslado."""
    if not is_transfer_order(proposal.work_order):
        return None

    try:
        transfer = proposal.work_order.transfer_detail
    except TransferDetail.DoesNotExist:
        return None

    if transfer.charge_mode == transfer.ChargeMode.UPFRONT_BASE:
        return transfer.base_fee_snapshot

    if transfer.charge_mode == transfer.ChargeMode.UPFRONT_FULL:
        return (
            transfer.customer_agreed_amount
            if transfer.customer_agreed_amount is not None
            else transfer.estimated_total
        )

    return None


@transaction.atomic
def accept_proposed_charge(*, proposal, user, amount, due_date, note=""):
    """Emite exactamente un cargo desde una propuesta todavía pendiente."""
    if user is None or user.pk is None:
        raise ValidationError("Debe indicar el usuario que acepta la propuesta.")

    locked = (
        ProposedCharge.objects
        .select_for_update()
        .select_related("customer", "subscription", "concept_item")
        .get(pk=proposal.pk)
    )

    if not locked.is_pending:
        raise ValidationError(
            f"La propuesta ya está {locked.get_status_display().lower()}."
        )

    try:
        amount = Decimal(amount)
    except Exception as exc:
        raise ValidationError("El monto propuesto no es válido.") from exc

    if is_transfer_order(locked.work_order):
        transfer = locked.work_order.transfer_detail

        if (
            transfer.charge_mode == transfer.ChargeMode.AFTER_TECHNICAL
            and locked.work_order.status != locked.work_order.Status.LIQUIDATED
        ):
            raise ValidationError(
                "Este traslado quedó definido para cobrar después de la "
                "constatación técnica. Debe liquidarse antes de emitir el cargo."
            )

        if (
            transfer.customer_agreed_amount is not None
            and amount != transfer.customer_agreed_amount
            and not (note or "").strip()
        ):
            raise ValidationError(
                "El monto es distinto al informado al abonado. "
                "Registre una observación que justifique el ajuste."
            )

    charge = create_manual_charge(
        customer=locked.customer,
        subscription=locked.subscription,
        concept=locked.concept,
        concept_item=locked.concept_item,
        description=locked.description,
        amount=amount,
        due_date=due_date or timezone.localdate(),
    )

    locked.status = ProposedCharge.Status.ACCEPTED
    locked.charge = charge
    locked.note = (note or "").strip()
    locked.resolved_by = user
    locked.resolved_at = timezone.now()
    locked.full_clean()
    locked.save()

    proposal.__dict__.update(locked.__dict__)
    return proposal


@transaction.atomic
def discard_proposed_charge(*, proposal, user, reason):
    """Descarta una propuesta con bloqueo y motivo obligatorio."""
    if user is None or user.pk is None:
        raise ValidationError("Debe indicar el usuario que descarta la propuesta.")

    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({
            "note": "Descartar una deuda de traslado exige un motivo.",
        })

    locked = ProposedCharge.objects.select_for_update().get(pk=proposal.pk)

    if not locked.is_pending:
        raise ValidationError(
            f"La propuesta ya está {locked.get_status_display().lower()}."
        )

    locked.status = ProposedCharge.Status.DISCARDED
    locked.note = reason
    locked.resolved_by = user
    locked.resolved_at = timezone.now()
    locked.full_clean()
    locked.save()

    proposal.__dict__.update(locked.__dict__)
    return proposal
