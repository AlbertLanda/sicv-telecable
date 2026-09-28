"""Averías y quién responde por ellas.

Una avería es trabajo físico sobre el servicio del abonado -internet o cable-
y llega al técnico por el mismo pool que una instalación. Lo propio de la
avería es su responsable: el operador lo declara al registrarla y el técnico
lo confirma o corrige en campo, que es donde se ve la causa.

Solo la responsabilidad del cliente mueve dinero. Cuando el técnico finaliza
la atención, lo que dejó instalado se valoriza al precio vigente del catálogo,
ese precio se congela, se suma la atención de S/ 10 y SICV emite
automáticamente la deuda. La propuesta queda como trazabilidad OT -> cargo,
no como una decisión pendiente de ventanilla.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import WorkOrderMaterialMovement
from apps.work_orders.evidence_files import validate_evidence_file
from apps.work_orders.models import (
    FAULT_ORDER_TYPE_CODES,
    FaultDetail,
    FaultResponsibilityEvidence,
    WorkOrder,
    WorkOrderLiquidation,
    WorkOrderLiquidationItem,
)
from apps.work_orders.services import create_work_order


# Atención de la avería cuando es responsabilidad del cliente. Se suma a los
# materiales y se congela en el detalle al finalizar la atención.
FAULT_CUSTOMER_SERVICE_FEE = Decimal("10.00")

# Desde que la atención termina, el técnico ya no puede editar materiales:
# lo que se le cobre al cliente deja de ser una estimación.
FIELD_CLOSED_STATUSES = frozenset({
    WorkOrder.Status.ATTENDED,
    WorkOrder.Status.LIQUIDATED,
})

MONEY_QUANTUM = Decimal("0.01")


def _money(value):
    return Decimal(value).quantize(MONEY_QUANTUM)


def fault_detail_for(order):
    """El detalle guardado, o uno sin guardar con la responsabilidad por defecto.

    Una avería que NOC derivó desde una incidencia nace sin detalle: se lee
    como responsabilidad de la empresa hasta que alguien diga otra cosa.
    """
    try:
        return FaultDetail.objects.get(work_order=order)
    except FaultDetail.DoesNotExist:
        return FaultDetail(work_order=order)


def customer_pays_fault(order):
    """La avería se le cobra al abonado: es suya según el último registro."""
    if not order.is_fault:
        return False
    return FaultDetail.objects.filter(
        work_order=order,
        responsibility=FaultDetail.Responsibility.CUSTOMER,
    ).exists()


def _save_responsibility(
    *,
    detail,
    user,
    source,
    responsibility,
    note,
    evidence_files,
):
    valid = {value for value, _label in FaultDetail.Responsibility.choices}
    if responsibility not in valid:
        raise ValidationError({
            "responsibility": "Seleccione la responsabilidad de la avería.",
        })

    files = [file for file in (evidence_files or []) if file]
    is_customer = responsibility == FaultDetail.Responsibility.CUSTOMER

    if files and not is_customer:
        raise ValidationError({
            "evidence": (
                "La evidencia sustenta la responsabilidad del cliente; "
                "no se adjunta a otra responsabilidad."
            ),
        })

    for file in files:
        validate_evidence_file(file)

    # El sustento explica por qué paga el abonado. Si la responsabilidad deja
    # de ser suya, un sustento que ya no aplica no se conserva como vigente.
    detail.responsibility = responsibility
    detail.responsibility_note = (note or "").strip() if is_customer else ""
    detail.responsibility_source = source
    detail.responsibility_set_by = user
    detail.responsibility_set_at = timezone.now()
    detail.full_clean()
    detail.save()

    for file in files:
        evidence = FaultResponsibilityEvidence(
            fault_detail=detail,
            file=file,
            source=source,
            uploaded_by=user,
        )
        evidence.full_clean()
        evidence.save()

    return detail


@transaction.atomic
def create_fault_work_order(
    *,
    subscription,
    order_type,
    created_by,
    customer=None,
    reason=None,
    responsibility=FaultDetail.Responsibility.COMPANY,
    responsibility_note="",
    evidence_files=(),
    priority=None,
    detail="",
    scheduled_at=None,
):
    """Registra una avería con la responsabilidad que declara el operador.

    La orden nace como cualquier otra -PENDING, sin técnico, atención FIELD-
    y entra al pool del técnico. Registrar la responsabilidad no emite deuda:
    lo que se cobre sale de la liquidación.
    """
    if order_type is None or order_type.code not in FAULT_ORDER_TYPE_CODES:
        raise ValidationError("Seleccione el tipo de avería.")

    order = create_work_order(
        subscription=subscription,
        order_type=order_type,
        created_by=created_by,
        customer=customer,
        reason=reason,
        attention_type=WorkOrder.AttentionType.FIELD,
        priority=priority,
        detail=detail,
        scheduled_at=scheduled_at,
    )

    _save_responsibility(
        detail=FaultDetail(work_order=order),
        user=created_by,
        source=FaultDetail.Source.OPERATOR,
        responsibility=responsibility,
        note=responsibility_note,
        evidence_files=evidence_files,
    )

    return order


@transaction.atomic
def set_fault_responsibility(
    *,
    order,
    user,
    responsibility,
    note="",
    evidence_files=(),
):
    """El técnico confirma o corrige en campo quién responde por la avería.

    Mismo criterio que la ficha técnica: solo el técnico asignado y solo
    mientras la orden está En atención. Lo que declare reemplaza lo que dijo
    el operador; las evidencias se acumulan.
    """
    if not order.is_fault:
        raise ValidationError(
            "Solo una orden de avería registra responsabilidad."
        )

    if order.status != WorkOrder.Status.IN_PROGRESS:
        raise ValidationError(
            "La responsabilidad solo puede registrarse con la orden En atención."
        )

    if user is None or order.assigned_technician_id != user.pk:
        raise ValidationError(
            "Solo el técnico asignado puede registrar la responsabilidad."
        )

    detail, _created = (
        FaultDetail.objects
        .select_for_update()
        .get_or_create(work_order=order)
    )

    return _save_responsibility(
        detail=detail,
        user=user,
        source=FaultDetail.Source.TECHNICIAN,
        responsibility=responsibility,
        note=note,
        evidence_files=evidence_files,
    )


def fault_material_price(movement):
    """Precio al abonado de un material de campo, o None si no se le cobra.

    Si el movimiento ya tiene precio facturable, ese valor es el snapshot
    histórico y manda sobre el catálogo actual. Mientras la atención sigue
    abierta se usa el precio vigente del catálogo. Lo retirado nunca se cobra.
    """
    if movement.movement_type != WorkOrderMaterialMovement.MovementType.INSTALLED:
        return None

    if movement.is_billable and movement.unit_price is not None:
        return movement.unit_price

    return movement.material.customer_price


def snapshot_fault_material_prices(order):
    """Congela precios cobrables cuando termina una avería del cliente."""
    if not customer_pays_fault(order):
        return []

    movements = (
        WorkOrderMaterialMovement.objects
        .select_for_update()
        .select_related("material")
        .filter(work_order=order)
        .order_by("pk")
    )
    snapped = []

    for movement in movements:
        if movement.movement_type != WorkOrderMaterialMovement.MovementType.INSTALLED:
            continue

        # Si ya existe snapshot, nunca se vuelve a leer el catálogo:
        # una liquidación posterior no puede revalorizar una avería atendida.
        if movement.is_billable and movement.unit_price is not None:
            snapped.append(movement)
            continue

        price = movement.material.customer_price
        if price is None:
            continue

        movement.is_billable = True
        movement.unit_price = price
        movement.save(
            update_fields=[
                "is_billable",
                "unit_price",
                "updated_at",
            ]
        )
        snapped.append(movement)

    return snapped


def _liquidation_or_none(order):
    try:
        return order.liquidation
    except WorkOrderLiquidation.DoesNotExist:
        return None


def fault_charge_breakdown(order):
    """Lo que se le propone cobrar al abonado por una avería suya.

    Mientras la atención sigue abierta usa el tarifario vigente. Al finalizar,
    los precios quedan congelados en los movimientos de material, así que el
    total ya no cambia aunque luego se edite el catálogo. Una vez liquidada,
    sale de la liquidación, que conserva cantidad y precio.
    """
    liquidation = _liquidation_or_none(order)
    detail = fault_detail_for(order)
    fee = (
        detail.service_fee_snapshot
        if detail.service_fee_snapshot is not None
        else FAULT_CUSTOMER_SERVICE_FEE
    )

    lines = []

    if liquidation is not None:
        for item in liquidation.items.all():
            if (
                not item.is_billable
                or item.movement_type != WorkOrderLiquidationItem.MovementType.USED
            ):
                continue
            lines.append({
                "code": item.material_code,
                "name": item.material_name,
                "quantity": item.quantity,
                "unit": item.get_unit_of_measure_display(),
                "unit_price": item.unit_price,
                "amount": _money(item.billable_amount),
            })
    else:
        movements = (
            order.field_material_movements
            .select_related("material")
            .order_by("material__name")
        )
        for movement in movements:
            price = fault_material_price(movement)
            if price is None:
                continue
            lines.append({
                "code": movement.material.code,
                "name": movement.material.name,
                "quantity": movement.quantity,
                "unit": movement.material.get_unit_of_measure_display(),
                "unit_price": price,
                "amount": _money(movement.quantity * price),
            })

    materials_total = sum(
        (line["amount"] for line in lines),
        Decimal("0.00"),
    )

    return {
        "fee": _money(fee),
        "lines": lines,
        "materials_total": _money(materials_total),
        "total": _money(fee + materials_total),
        "is_final": (
            liquidation is not None
            or order.status in FIELD_CLOSED_STATUSES
        ),
    }


def propose_fault_charge_on_close(*, order, user=None):
    """Emite automáticamente la deuda al cerrar una avería del cliente.

    La propuesta se conserva como vínculo auditable entre OT y cargo. Volver
    a llamar esta función al liquidar es idempotente: si ya fue aceptada, no
    se emite otra deuda.
    """
    if not customer_pays_fault(order):
        return None

    detail = FaultDetail.objects.select_for_update().get(work_order=order)
    if detail.service_fee_snapshot is None:
        detail.service_fee_snapshot = FAULT_CUSTOMER_SERVICE_FEE
        detail.save(update_fields=["service_fee_snapshot", "updated_at"])

    snapshot_fault_material_prices(order)

    from apps.payments.proposals import (
        accept_proposed_charge,
        propose_fault_charge,
    )

    proposal = propose_fault_charge(work_order=order)
    if not proposal.is_pending:
        return proposal

    actor = (
        user
        or detail.responsibility_set_by
        or order.assigned_technician
        or order.created_by
    )
    if actor is None:
        raise ValidationError(
            "No se pudo identificar al usuario que originó el cierre de la avería."
        )

    breakdown = fault_charge_breakdown(order)
    accept_proposed_charge(
        proposal=proposal,
        user=actor,
        amount=breakdown["total"],
        due_date=timezone.localdate(),
        note="Cargo automático por avería atribuible al cliente.",
    )
    proposal.refresh_from_db()
    return proposal
