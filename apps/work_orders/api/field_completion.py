"""Ayudantes del cierre técnico para el canal móvil.

Mantiene separadas tres responsabilidades:
- la atención cambia IN_PROGRESS -> ATTENDED mediante services.attend_order();
- la liquidación cambia ATTENDED -> LIQUIDATED mediante services.liquidate_order();
- este módulo solo arma el resumen de campo y traduce los movimientos ya
  registrados a los items trazables de la liquidación.
"""

from apps.inventory.models import WorkOrderMaterialMovement
from apps.work_orders.faults import customer_pays_fault, fault_material_price
from apps.work_orders.models import WorkOrder, WorkOrderLiquidationItem


def field_completion_summary(order: WorkOrder):
    """Resumen no bloqueante de lo capturado antes de finalizar la atención."""
    try:
        sheet = order.field_sheet
    except WorkOrder.field_sheet.RelatedObjectDoesNotExist:
        sheet = None

    field_values = []
    if sheet is not None:
        field_values = [
            sheet.nap,
            sheet.terminal,
            sheet.equipment_code,
            sheet.seal_number,
            sheet.notes,
        ]

    movements = order.field_material_movements.all()

    return {
        "field_sheet_registered": bool(sheet and any(field_values)),
        "installed_materials": movements.filter(
            movement_type=WorkOrderMaterialMovement.MovementType.INSTALLED,
        ).count(),
        "removed_materials": movements.filter(
            movement_type=WorkOrderMaterialMovement.MovementType.REMOVED,
        ).count(),
        "meter_records": order.installation_material_usages.count(),
        "evidences": order.evidences.count(),
    }


def liquidation_items_from_field(order: WorkOrder):
    """Convierte materiales de campo en snapshots de WorkOrderLiquidationItem.

    En una avería responsabilidad del cliente, lo instalado con precio en el
    catálogo llega facturable a ese precio: el técnico no lo marca ni lo
    escribe, y la liquidación congela el precio del día.
    """
    items = []
    movements = (
        order.field_material_movements
        .select_related("material")
        .order_by("movement_type", "material__name")
    )
    charges_customer = customer_pays_fault(order)

    for movement in movements:
        movement_type = (
            WorkOrderLiquidationItem.MovementType.USED
            if movement.movement_type == WorkOrderMaterialMovement.MovementType.INSTALLED
            else WorkOrderLiquidationItem.MovementType.REMOVED
        )
        is_billable = movement.is_billable
        unit_price = movement.unit_price

        if charges_customer:
            price = fault_material_price(movement)
            if price is not None:
                is_billable = True
                unit_price = price

        items.append(
            {
                "movement_type": movement_type,
                "material_code": movement.material.code,
                "material_name": movement.material.name,
                "quantity": movement.quantity,
                "unit_of_measure": movement.material.unit_of_measure,
                "is_billable": is_billable,
                "unit_price": unit_price,
                "remarks": movement.remarks,
            }
        )

    return items


def liquidation_technical_data_from_field(order: WorkOrder):
    """Reutiliza la ficha técnica como snapshot base de la liquidación."""
    try:
        sheet = order.field_sheet
    except WorkOrder.field_sheet.RelatedObjectDoesNotExist:
        return {}

    return {
        "network_element": sheet.nap,
        "network_port": sheet.terminal,
        "equipment_serial": sheet.equipment_code,
    }
