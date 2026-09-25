from django.core.exceptions import ValidationError
from django.db import transaction

from apps.inventory.models import Material, WorkOrderMaterialMovement
from apps.work_orders.models import WorkOrder


# Los tres cables del catálogo operativo son los mismos tres materiales que
# tienen reglas comerciales de metraje/exceso. El técnico los registra una
# sola vez como material instalado y la cantidad (en metros) alimenta también
# el cálculo de exceso. Los códigos son estables y evitan inferir por nombre.
INSTALLATION_METER_MATERIALS = {
    "CABLE_UTP": "UTP",
    "CABLE_RG6": "RG6",
    "FIBRA_DROP": "DROP",
}


def _validate_field_material_write(work_order, user):
    if work_order.status != WorkOrder.Status.IN_PROGRESS:
        raise ValidationError(
            "Los materiales solo pueden modificarse cuando la orden está En atención."
        )
    if work_order.assigned_technician_id != getattr(user, "pk", None):
        raise ValidationError(
            "Solo el técnico asignado puede registrar materiales de esta orden."
        )


def _installation_meter_material(work_order, material, movement_type):
    """Devuelve el código comercial de metraje si este movimiento lo alimenta."""
    if movement_type != WorkOrderMaterialMovement.MovementType.INSTALLED:
        return None
    if work_order.order_type.code != "INSTALLATION":
        return None
    if material.unit_of_measure != Material.Unit.METER:
        return None
    return INSTALLATION_METER_MATERIALS.get(material.code)


def _sync_installation_meter_usage(work_order, material, movement_type, quantity):
    """Sincroniza el metraje/exceso desde el material instalado.

    Si todavía no existe una regla comercial para ese cable, el registro del
    material sigue siendo válido: simplemente no hay exceso que calcular aún.
    Esto evita bloquear el trabajo de campo por una configuración comercial
    ausente.
    """
    meter_material = _installation_meter_material(
        work_order,
        material,
        movement_type,
    )
    if meter_material is None:
        return

    # Imports locales para mantener el módulo de inventario desacoplado al
    # cargar modelos y evitar ciclos entre inventory y services.
    from apps.services.installation_rules import (
        record_installation_material_usage,
        resolve_installation_material_rule,
    )

    rule = resolve_installation_material_rule(
        work_order=work_order,
        material=meter_material,
    )
    if rule is None:
        return

    record_installation_material_usage(
        work_order=work_order,
        material=meter_material,
        meters_used=quantity,
    )


def _delete_installation_meter_usage(work_order, material, movement_type):
    """Quita el metraje automático cuando se elimina el cable instalado."""
    meter_material = _installation_meter_material(
        work_order,
        material,
        movement_type,
    )
    if meter_material is None:
        return

    work_order.installation_material_usages.filter(
        rule__material=meter_material,
    ).delete()


@transaction.atomic
def record_work_order_material(
    *,
    work_order,
    material,
    movement_type,
    quantity,
    user,
    remarks="",
    is_billable=False,
    unit_price=None,
):
    """Crea o actualiza un material instalado/retirado durante la atención.

    Un mismo material aparece como máximo una vez por sentido en cada OT. Si
    el técnico corrige la cantidad, se actualiza la fila existente en lugar de
    generar duplicados. Esto es trazabilidad operativa; todavía no descuenta ni
    devuelve stock de almacén.

    En órdenes de instalación, UTP/RG6/Drop instalados se registran en metros y
    alimentan automáticamente la regla de metraje/exceso. No se pide un segundo
    registro al técnico.
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

    is_billable = bool(is_billable)
    if is_billable:
        if work_order.order_type.code != "TRANSFER":
            raise ValidationError(
                "Solo los materiales de una orden de traslado pueden "
                "marcarse como facturables al abonado."
            )
        if movement_type != WorkOrderMaterialMovement.MovementType.INSTALLED:
            raise ValidationError(
                "Solo un material instalado puede marcarse como facturable."
            )
        if unit_price is None or unit_price <= 0:
            raise ValidationError(
                "Un material facturable debe indicar un precio unitario mayor que cero."
            )
    else:
        unit_price = None

    movement, _created = WorkOrderMaterialMovement.objects.update_or_create(
        work_order=work_order,
        material=material,
        movement_type=movement_type,
        defaults={
            "quantity": quantity,
            "is_billable": is_billable,
            "unit_price": unit_price,
            "remarks": remarks or "",
            "recorded_by": user,
        },
    )

    _sync_installation_meter_usage(
        work_order,
        material,
        movement_type,
        quantity,
    )
    return movement


@transaction.atomic
def delete_work_order_material(*, work_order, movement, user):
    _validate_field_material_write(work_order, user)
    if movement.work_order_id != work_order.pk:
        raise ValidationError("El material no pertenece a esta orden.")

    _delete_installation_meter_usage(
        work_order,
        movement.material,
        movement.movement_type,
    )
    movement.delete()
