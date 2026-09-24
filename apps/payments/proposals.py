"""
Deudas que una orden de trabajo propone y la ventanilla resuelve.

Hoy solo hay una: el traslado. Registrar la orden deja constancia de que ese
abonado tiene un traslado por cobrar, y quien atiende decide cuánto y lo
acepta. El monto no lo pone el sistema porque no lo sabe: depende del caso, y
una cifra puesta de oficio saldría en la deuda del abonado como si fuera la
oficial.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Charge, ChargeConcept, ProposedCharge
from .services import create_manual_charge


# El motivo del catálogo operativo que dispara la propuesta. TRASLADO es un
# motivo de REQUERIMIENTO, no un tipo de orden: se lee del motivo elegido por
# el ATC, que es donde el operador lo declara.
TRANSFER_REASON_CODE = "TRANSFER"

# El concepto con el que se emite el cargo, ya sembrado en el catálogo
# comercial.
TRANSFER_CONCEPT_CODE = "traslado"

TRANSFER_DESCRIPTION = "TRASLADO DE DOMICILIO"


def is_transfer_order(work_order):
    """Si esa orden es un traslado, según el motivo que declaró el ATC."""
    return (
        work_order.reason_id is not None
        and work_order.reason.code == TRANSFER_REASON_CODE
    )


def transfer_concept():
    return ChargeConcept.objects.filter(
        code=TRANSFER_CONCEPT_CODE, is_active=True
    ).first()


@transaction.atomic
def propose_transfer_charge(*, work_order):
    """Deja el traslado propuesto, sin monto y sin tocar el saldo.

    Devuelve la propuesta, o ``None`` si la orden no es un traslado. No falla
    cuando ya existe: registrar dos veces la misma orden no debe dejar al
    abonado con dos traslados por cobrar, y la restricción única de
    (orden, concepto) lo respalda en la base.
    """
    if not is_transfer_order(work_order):
        return None

    concept = transfer_concept()

    existing = ProposedCharge.objects.filter(
        work_order=work_order, concept_item=concept
    ).first()

    if existing is not None:
        return existing

    proposal = ProposedCharge(
        customer_id=work_order.subscription.customer_id,
        subscription=work_order.subscription,
        work_order=work_order,
        concept=concept.family if concept else Charge.Concept.OTHER,
        concept_item=concept,
        description=TRANSFER_DESCRIPTION,
    )
    proposal.full_clean()
    proposal.save()

    return proposal


def pending_proposals(customer):
    """Las propuestas que esperan una decisión, para pintarlas sobre la tabla."""
    return (
        ProposedCharge.objects
        .filter(customer=customer, status=ProposedCharge.Status.PENDING)
        .select_related("work_order", "concept_item")
        .order_by("-created_at", "-pk")
    )


@transaction.atomic
def accept_proposed_charge(*, proposal, user, amount, due_date, note=""):
    """Emite el cargo con el monto que puso el operador."""
    if user is None or user.pk is None:
        raise ValidationError("Debe indicar el usuario que acepta la propuesta.")

    if not proposal.is_pending:
        raise ValidationError(
            f"La propuesta ya está {proposal.get_status_display().lower()}."
        )

    charge = create_manual_charge(
        customer=proposal.customer,
        subscription=proposal.subscription,
        concept=proposal.concept,
        concept_item=proposal.concept_item,
        description=proposal.description,
        amount=amount,
        due_date=due_date or timezone.localdate(),
    )

    proposal.status = ProposedCharge.Status.ACCEPTED
    proposal.charge = charge
    proposal.note = (note or "").strip()
    proposal.resolved_by = user
    proposal.resolved_at = timezone.now()
    proposal.full_clean()
    proposal.save()

    return proposal


@transaction.atomic
def discard_proposed_charge(*, proposal, user, reason):
    """Renuncia a cobrar la propuesta, dejando dicho por qué y quién."""
    if user is None or user.pk is None:
        raise ValidationError("Debe indicar el usuario que descarta la propuesta.")

    if not proposal.is_pending:
        raise ValidationError(
            f"La propuesta ya está {proposal.get_status_display().lower()}."
        )

    reason = (reason or "").strip()

    if not reason:
        raise ValidationError({
            "note": "Descartar una deuda de traslado exige un motivo.",
        })

    proposal.status = ProposedCharge.Status.DISCARDED
    proposal.note = reason
    proposal.resolved_by = user
    proposal.resolved_at = timezone.now()
    proposal.full_clean()
    proposal.save()

    return proposal
