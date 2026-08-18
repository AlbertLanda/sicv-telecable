from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.services.models import Subscription
from apps.work_orders.models import (
    WorkOrder,
    WorkOrderLiquidation,
    WorkOrderLiquidationItem,
)


@transaction.atomic
def apply_order_result(order: WorkOrder):
    if not order.result:
        raise ValidationError(
            "La orden debe tener un resultado antes de aplicar sus efectos."
        )

    if order.result.order_type_id != order.order_type_id:
        raise ValidationError(
            "El resultado seleccionado no corresponde al tipo de orden."
        )

    order_type_code = order.order_type.code
    result_code = order.result.code

    if order_type_code == "INSTALLATION":
        _apply_installation_result(order, result_code)

    elif order_type_code == "CUT":
        _apply_cut_result(order, result_code)

    elif order_type_code == "RECONNECTION":
        _apply_reconnection_result(order, result_code)

    elif order_type_code == "TRANSFER":
        _apply_transfer_result(order, result_code)

@transaction.atomic
def start_order_attention(order: WorkOrder, user=None, remarks=""):
    """
    Inicia formalmente la atención de una orden.

    Usa el workflow oficial de WorkOrder y aplica efectos
    adicionales sobre la suscripción cuando corresponda.
    """
    order.start_attention(
        user=user,
        remarks=remarks,
    )

    if (
        order.order_type.code == "INSTALLATION"
        and order.subscription.status == Subscription.Status.PRESALE
    ):
        order.subscription.status = Subscription.Status.INSTALLATION

        order.subscription.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

    return order

@transaction.atomic
def attend_order(order: WorkOrder, result, user=None, remarks=""):
    """
    Cierra operativamente la atención de una orden.

    Registra el resultado, mueve la orden a ATTENDED por el mecanismo
    oficial de transición y aplica los efectos sobre la suscripción
    delegando en apply_order_result(). Las reglas de negocio no se
    duplican aquí: viven en las funciones _apply_* de este módulo.
    """
    if result is None:
        raise ValidationError(
            "Debe indicar el resultado de la atención."
        )

    if order.status != WorkOrder.Status.IN_PROGRESS:
        raise ValidationError(
            "Solo una orden en atención puede finalizarse como atendida."
        )

    if result.order_type_id != order.order_type_id:
        raise ValidationError(
            "El resultado seleccionado no corresponde al tipo de orden."
        )

    order.result = result
    order.save(update_fields=["result", "updated_at"])

    order.change_status(
        WorkOrder.Status.ATTENDED,
        user=user,
        remarks=remarks,
    )

    apply_order_result(order)

    return order


# Campos técnicos opcionales que liquidate_order() acepta y traslada tal cual
# a WorkOrderLiquidation. Se declaran aquí para rechazar cualquier clave
# desconocida antes de tocar la base de datos.
LIQUIDATION_TECHNICAL_FIELDS = (
    "network_element",
    "network_port",
    "equipment_serial",
    "signal_level_dbm",
    "cable_meters_used",
    "krill_reference",
)


@transaction.atomic
def liquidate_order(
    order: WorkOrder,
    user,
    technical_notes="",
    resolution_detail="",
    items=None,
    remarks="",
    **technical_data,
):
    """
    Liquidación técnica de una orden ya atendida.

    Registra en un solo movimiento atómico la WorkOrderLiquidation, los
    materiales/equipos declarados y la transición ATTENDED -> LIQUIDATED
    por el mecanismo oficial change_status().

    Liquidar documenta la atención; **no** valida (NOC ni almacén) ni cierra
    la orden, y los materiales declarados no mueven inventario.

    `items` es una lista de diccionarios con las claves de
    WorkOrderLiquidationItem (movement_type, material_name, quantity,
    unit_of_measure, material_code, remarks).
    """
    if order.status != WorkOrder.Status.ATTENDED:
        raise ValidationError(
            "Solo una orden atendida puede liquidarse. "
            f"Estado actual: {order.get_status_display()}."
        )

    if order.is_liquidated:
        raise ValidationError(
            "La orden ya cuenta con una liquidación registrada."
        )

    if user is None:
        raise ValidationError(
            "Debe indicar el usuario responsable de la liquidación."
        )

    if not user.is_active:
        raise ValidationError(
            "El usuario responsable de la liquidación debe estar activo."
        )

    if not resolution_detail or not resolution_detail.strip():
        raise ValidationError(
            "Debe describir la solución o el trabajo ejecutado en campo."
        )

    unknown_fields = set(technical_data) - set(LIQUIDATION_TECHNICAL_FIELDS)

    if unknown_fields:
        raise ValidationError(
            "Datos técnicos no reconocidos en la liquidación: "
            f"{', '.join(sorted(unknown_fields))}."
        )

    liquidation = WorkOrderLiquidation(
        work_order=order,
        liquidated_by=user,
        liquidated_at=timezone.now(),
        resolution_detail=resolution_detail,
        technical_notes=technical_notes,
        **technical_data,
    )

    liquidation.full_clean(exclude=["work_order"])
    liquidation.save()

    for item_data in items or []:
        item = WorkOrderLiquidationItem(liquidation=liquidation, **item_data)
        item.full_clean(exclude=["liquidation"])
        item.save()

    order.change_status(
        WorkOrder.Status.LIQUIDATED,
        user=user,
        remarks=remarks,
    )

    return liquidation


def _apply_installation_result(order, result_code):
    subscription = order.subscription

    if result_code == "SUCCESSFUL":
        subscription.status = Subscription.Status.ACTIVE
        subscription.installation_date = timezone.localdate()

        subscription.save(
            update_fields=[
                "status",
                "installation_date",
                "updated_at",
            ]
        )

def _apply_cut_result(order, result_code):
    if result_code != "SUCCESSFUL":
        return

    if not order.subtype:
        raise ValidationError(
            "Las órdenes de corte deben indicar si el corte es temporal o definitivo."
        )

    try:
        cut_detail = order.cut_detail
    except WorkOrder.cut_detail.RelatedObjectDoesNotExist:
        raise ValidationError(
            "La orden de corte debe tener un detalle de corte."
        )

    cut_detail.full_clean()

    subscription = order.subscription
    subtype_code = order.subtype.code

    if subtype_code == "TEMPORARY":
        subscription.status = Subscription.Status.SUSPENDED
        subscription.cut_date = timezone.localdate()

    elif subtype_code == "DEFINITIVE":
        subscription.status = Subscription.Status.CANCELLED
        subscription.cut_date = timezone.localdate()

    else:
        raise ValidationError(
            "El subtipo de corte no es válido."
        )

    subscription.save(
        update_fields=[
            "status",
            "cut_date",
            "updated_at",
        ]
    )

def _apply_reconnection_result(order, result_code):
    if result_code != "SUCCESSFUL":
        return

    subscription = order.subscription

    subscription.status = Subscription.Status.ACTIVE
    subscription.reconnection_date = timezone.localdate()

    subscription.save(
        update_fields=[
            "status",
            "reconnection_date",
            "updated_at",
        ]
    )

def _apply_transfer_result(order, result_code):
    if result_code != "SUCCESSFUL":
        return

    if not order.subtype:
        raise ValidationError(
            "La orden de traslado debe indicar si es interna o externa."
        )

    try:
        transfer_detail = order.transfer_detail
    except WorkOrder.transfer_detail.RelatedObjectDoesNotExist:
        raise ValidationError(
            "La orden de traslado debe tener un detalle de traslado."
        )

    transfer_detail.full_clean()

    subtype_code = order.subtype.code
    subscription = order.subscription

    if subtype_code == "INTERNAL":
        # En un traslado interno la dirección del servicio NO cambia.
        return

    if subtype_code == "EXTERNAL":
        subscription.address = transfer_detail.new_address

        subscription.save(
            update_fields=[
                "address",
                "updated_at",
            ]
        )

        return

    raise ValidationError(
        "El subtipo de traslado no es válido."
    )