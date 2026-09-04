from django.core.exceptions import ValidationError
from django.db import transaction

from apps.inventory.models import Material, WorkOrderMaterialMovement
from apps.work_orders.models import WorkOrder


def _validate_field_material_write(work_order, user):
    if work_order.status != WorkOrder.Status.IN_PROGRESS:
        raise ValidationError(
            "Los materiales solo pueden modificarse cuando la orden está En atención."
        )
    if work_order.assigned_technician_id != getattr(user, "pk", None):
        raise ValidationError(
            "Solo el técnico asignado puede registrar materiales de esta orden."
        )


@transaction.atomic
def record_work_order_material(
    *,
    work_order,
    material,
    movement_type,
    quantity,
    user,
    remarks="",
):
    """Crea o actualiza un material instalado/retirado durante la atención.

    Un mismo material aparece como máximo una vez por sentido en cada OT. Si
    el técnico corrige la cantidad, se actualiza la fila existente en lugar de
    generar duplicados. Esto es trazabilidad operativa; todavía no descuenta ni
    devuelve stock de almacén.
    """
    _validate_field_material_write(work_order, user)

    if not isinstance(material, Material) or material.pk is None or not material.is_active:
        raise ValidationError("El material seleccionado no está disponible.")

    valid_movements = {
        value for value, _label in WorkOrderMaterialMovement.MovementType.choices
    }
    if movement_type not in valid_movements:
        raise ValidationError("El tipo de movimiento de material no es válido.")

    if quantity is None or quantity <= 0:
        raise ValidationError("La cantidad debe ser mayor a cero.")

    movement, _created = WorkOrderMaterialMovement.objects.update_or_create(
        work_order=work_order,
        material=material,
        movement_type=movement_type,
        defaults={
            "quantity": quantity,
            "remarks": remarks or "",
            "recorded_by": user,
        },
    )
    return movement


@transaction.atomic
def delete_work_order_material(*, work_order, movement, user):
    _validate_field_material_write(work_order, user)
    if movement.work_order_id != work_order.pk:
        raise ValidationError("El material no pertenece a esta orden.")
    movement.delete()
