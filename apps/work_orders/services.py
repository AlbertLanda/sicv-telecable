from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.services.models import Subscription
from apps.work_orders.models import (
    WorkOrder,
    WorkOrderLiquidation,
    WorkOrderLiquidationCorrection,
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


# --- Ciclo de revisión de la liquidación ------------------------------------
#
# Una sola validación funcional y una sola oportunidad de corrección:
#
#     LIQUIDATED -> SUBMITTED -> VALIDATED
#                     |
#                     +-> CORRECTION_REQUESTED -> RESUBMITTED -> VALIDATED
#
# Estos servicios son el único camino legítimo para mover review_status. El
# Admin y las vistas no lo tocan directamente.

# Permiso funcional del validador. NO se consulta el rol del usuario: quien
# tenga el permiso valida, venga de NOC, de almacén o de donde sea.
LIQUIDATION_VALIDATION_PERMISSION = "work_orders.validate_liquidation"

# Campos que el técnico puede rectificar en su única corrección.
LIQUIDATION_CORRECTABLE_FIELDS = (
    "resolution_detail",
    "technical_notes",
) + LIQUIDATION_TECHNICAL_FIELDS


def _require_active_user(user, action):
    if user is None:
        raise ValidationError(
            f"Debe indicar el usuario que {action}."
        )

    if not user.is_active:
        raise ValidationError(
            f"El usuario que {action} debe estar activo."
        )


def _require_validator(user):
    """Autoriza por permiso funcional, nunca por rol o área."""
    _require_active_user(user, "valida la liquidación")

    if not user.has_perm(LIQUIDATION_VALIDATION_PERMISSION):
        raise ValidationError(
            "El usuario no está autorizado para validar liquidaciones. "
            f"Requiere el permiso {LIQUIDATION_VALIDATION_PERMISSION}."
        )


def _require_liquidation_owner(liquidation, user):
    """
    Solo el técnico que realizó la liquidación puede operar sobre ella.
    """
    _require_active_user(user, "corrige la liquidación")

    if user.pk != liquidation.liquidated_by_id:
        raise ValidationError(
            "Solo el técnico que realizó la liquidación puede corregirla."
        )


def _snapshot_value(value):
    """Serializa un valor a texto para poder guardarlo en el historial JSON."""
    if value is None:
        return ""

    return str(value)


def _snapshot_items(liquidation):
    return [
        {
            "movement_type": item.movement_type,
            "material_code": item.material_code,
            "material_name": item.material_name,
            "quantity": _snapshot_value(item.quantity),
            "unit_of_measure": item.unit_of_measure,
            "remarks": item.remarks,
        }
        for item in liquidation.items.all()
    ]


@transaction.atomic
def submit_liquidation(liquidation: WorkOrderLiquidation, user, remarks=""):
    """
    Envía formalmente la liquidación a revisión: LIQUIDATED -> SUBMITTED.

    A partir de aquí la liquidación queda bloqueada: solo vuelve a ser
    editable si el validador solicita la única corrección disponible.
    """
    if liquidation.pk is None:
        raise ValidationError(
            "Solo puede enviarse una liquidación ya registrada."
        )

    if liquidation.review_status != WorkOrderLiquidation.ReviewStatus.LIQUIDATED:
        raise ValidationError(
            "Solo una liquidación recién registrada puede enviarse a revisión. "
            f"Estado actual: {liquidation.get_review_status_display()}."
        )

    _require_liquidation_owner(liquidation, user)

    if not liquidation.resolution_detail.strip():
        raise ValidationError(
            "La liquidación debe estar completa antes de enviarse a revisión."
        )

    liquidation.review_status = WorkOrderLiquidation.ReviewStatus.SUBMITTED
    liquidation.submitted_by = user
    liquidation.submitted_at = timezone.now()
    liquidation.submission_remarks = remarks

    liquidation.full_clean(exclude=["work_order"])
    liquidation.save(
        update_fields=[
            "review_status",
            "submitted_by",
            "submitted_at",
            "submission_remarks",
            "updated_at",
        ]
    )

    return liquidation


@transaction.atomic
def request_liquidation_correction(
    liquidation: WorkOrderLiquidation,
    validator,
    reason,
):
    """
    El validador detecta un error y abre la única ventana de corrección:
    SUBMITTED -> CORRECTION_REQUESTED.

    El motivo es obligatorio: sin él el técnico no sabe qué rectificar y la
    auditoría queda coja.
    """
    if liquidation.review_status != WorkOrderLiquidation.ReviewStatus.SUBMITTED:
        raise ValidationError(
            "Solo puede solicitarse corrección sobre una liquidación enviada. "
            f"Estado actual: {liquidation.get_review_status_display()}."
        )

    _require_validator(validator)

    if not reason or not reason.strip():
        raise ValidationError(
            "Debe indicar el motivo de la corrección solicitada."
        )

    if liquidation.correction_count != 0:
        raise ValidationError(
            "Esta liquidación ya consumió su única oportunidad de corrección."
        )

    liquidation.review_status = (
        WorkOrderLiquidation.ReviewStatus.CORRECTION_REQUESTED
    )
    liquidation.correction_reason = reason.strip()
    liquidation.correction_requested_by = validator
    liquidation.correction_requested_at = timezone.now()

    liquidation.full_clean(exclude=["work_order"])
    liquidation.save(
        update_fields=[
            "review_status",
            "correction_reason",
            "correction_requested_by",
            "correction_requested_at",
            "updated_at",
        ]
    )

    return liquidation


@transaction.atomic
def resubmit_liquidation(
    liquidation: WorkOrderLiquidation,
    technician,
    changes=None,
    remarks="",
):
    """
    El técnico consume su única corrección y reenvía:
    CORRECTION_REQUESTED -> RESUBMITTED.

    Todo ocurre en un solo movimiento atómico: si algo falla no se aplica
    ningún cambio, no se incrementa correction_count y la liquidación sigue
    en CORRECTION_REQUESTED con su oportunidad intacta.

    `changes` acepta los campos de LIQUIDATION_CORRECTABLE_FIELDS y,
    opcionalmente, la clave "items" para redeclarar los materiales.
    """
    if liquidation.review_status != (
        WorkOrderLiquidation.ReviewStatus.CORRECTION_REQUESTED
    ):
        raise ValidationError(
            "Solo puede reenviarse una liquidación con corrección solicitada. "
            f"Estado actual: {liquidation.get_review_status_display()}."
        )

    # Se verifica ANTES de consumir la oportunidad.
    if liquidation.correction_count != 0:
        raise ValidationError(
            "Esta liquidación ya consumió su única oportunidad de corrección."
        )

    _require_liquidation_owner(liquidation, technician)

    changes = dict(changes or {})
    new_items = changes.pop("items", None)

    unknown_fields = set(changes) - set(LIQUIDATION_CORRECTABLE_FIELDS)

    if unknown_fields:
        raise ValidationError(
            "Campos no corregibles en la liquidación: "
            f"{', '.join(sorted(unknown_fields))}."
        )

    # --- Snapshot previo: solo lo que realmente cambia --------------------
    values_before = {}
    values_after = {}

    for field, new_value in changes.items():
        old_value = _snapshot_value(getattr(liquidation, field))
        setattr(liquidation, field, new_value)
        applied_value = _snapshot_value(getattr(liquidation, field))

        if old_value != applied_value:
            values_before[field] = old_value
            values_after[field] = applied_value

    items_before = _snapshot_items(liquidation) if new_items is not None else []

    liquidation.correction_count = 1
    liquidation.resubmitted_at = timezone.now()
    liquidation.review_status = WorkOrderLiquidation.ReviewStatus.RESUBMITTED

    liquidation.full_clean(exclude=["work_order"])
    liquidation.save()

    # --- Materiales redeclarados ------------------------------------------
    if new_items is not None:
        liquidation.items.all().delete()

        for item_data in new_items:
            item = WorkOrderLiquidationItem(
                liquidation=liquidation,
                **item_data,
            )
            item.full_clean(exclude=["liquidation"])
            item.save()

    items_after = _snapshot_items(liquidation) if new_items is not None else []

    # --- Traza de la corrección -------------------------------------------
    correction = WorkOrderLiquidationCorrection(
        liquidation=liquidation,
        corrected_by=technician,
        correction_reason=liquidation.correction_reason,
        values_before=values_before,
        values_after=values_after,
        items_before=items_before,
        items_after=items_after,
        remarks=remarks,
    )
    correction.full_clean(exclude=["liquidation", "corrected_by"])
    correction.save()

    return liquidation


@transaction.atomic
def validate_liquidation(liquidation: WorkOrderLiquidation, validator, remarks=""):
    """
    Validación única y final: SUBMITTED o RESUBMITTED -> VALIDATED.

    Al validar, la liquidación queda bloqueada para siempre. La orden NO se
    cierra aquí: el cierre definitivo de WorkOrder es una fase posterior
    todavía sin definir.
    """
    if not liquidation.can_be_validated:
        raise ValidationError(
            "Solo puede validarse una liquidación enviada o reenviada. "
            f"Estado actual: {liquidation.get_review_status_display()}."
        )

    _require_validator(validator)

    liquidation.review_status = WorkOrderLiquidation.ReviewStatus.VALIDATED
    liquidation.validated_by = validator
    liquidation.validated_at = timezone.now()
    liquidation.validation_remarks = remarks

    liquidation.full_clean(exclude=["work_order"])
    liquidation.save(
        update_fields=[
            "review_status",
            "validated_by",
            "validated_at",
            "validation_remarks",
            "updated_at",
        ]
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