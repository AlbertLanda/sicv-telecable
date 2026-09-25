"""Averías y quién responde por ellas.

Una avería es trabajo físico sobre el servicio del abonado -internet o cable-
y llega al técnico por el mismo pool que una instalación. Lo propio de la
avería es su responsable: el operador lo declara al registrarla y el técnico
lo confirma o corrige en campo, que es donde se ve la causa.

Solo la responsabilidad del cliente mueve dinero, y nunca de oficio. Cuando
el técnico finaliza la atención, lo que dejó instalado se valoriza al precio
del catálogo de materiales, se le suma la atención de la avería y todo queda
como deuda propuesta. Emitirla o descartarla lo decide la ventanilla.
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

    Se cobra lo instalado que tiene precio en el catálogo. Lo retirado nunca
    se cobra. Que la avería sea del cliente lo decide quien llama.
    """
    if (
        movement.movement_type != WorkOrderMaterialMovement.MovementType.INSTALLED
        or movement.material.customer_price is None
    ):
        return None
    return movement.material.customer_price


def _liquidation_or_none(order):
    try:
        return order.liquidation
    except WorkOrderLiquidation.DoesNotExist:
        return None


def fault_charge_breakdown(order):
    """Lo que se le propone cobrar al abonado por una avería suya.

    Sale de los materiales que el técnico registró, a los precios vigentes
    del catálogo. Mientras la atención sigue abierta es una estimación; al
    finalizarla los materiales ya no cambian y el monto es definitivo. Una
    vez liquidada, sale de la liquidación, que congela cantidad y precio.
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


def propose_fault_charge_on_close(*, order):
    """Al terminar la atención de una avería del cliente, deja propuesta su deuda.

    Se llama al finalizar la atención -desde ahí los materiales ya no
    cambian- y otra vez al liquidar, sin duplicar nada: la segunda llamada
    cubre una avería que se finalizó antes de que existiera la primera.
    Congela la atención de la avería; emitir la deuda es decisión de la
    ventanilla.
    """
    if not customer_pays_fault(order):
        return None

    detail = FaultDetail.objects.select_for_update().get(work_order=order)
    if detail.service_fee_snapshot is None:
        detail.service_fee_snapshot = FAULT_CUSTOMER_SERVICE_FEE
        detail.save(update_fields=["service_fee_snapshot", "updated_at"])

    # La importación es local a propósito: `payments` apunta a `work_orders`
    # -la propuesta cuelga de la orden- y subirla al módulo cerraría el ciclo.
    from apps.payments.proposals import propose_fault_charge

    return propose_fault_charge(work_order=order)
