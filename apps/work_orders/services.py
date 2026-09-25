from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.customers.models import CustomerAddress
from apps.services.models import Subscription
from apps.work_orders.models import (
    DEFINITIVE_CUT_REASONS,
    TEMPORARY_CUT_REASONS,
    IncidentDetail,
    OrderType,
    OutsidePlantDetail,
    TransferDetail,
    WorkOrder,
    WorkOrderParticipation,
    WorkOrderEvidence,
    WorkOrderFieldSheet,
    WorkOrderLiquidation,
    WorkOrderLiquidationCorrection,
    WorkOrderLiquidationItem,
    WorkOrderSequence,
)


# --- Creación de órdenes de trabajo -----------------------------------------
#
# create_work_order() es el ÚNICO camino legítimo para registrar una OT.
# Vistas, API e interfaz deben consumirlo en lugar de
# WorkOrder.objects.create().
#
# Crear la orden solo registra la necesidad de trabajo: no inicia la atención
# ni mueve el estado de la suscripción. Una OT de instalación nacida de una
# suscripción en PRESALE la deja en PRESALE. Los cambios operativos ocurren
# después, en start_order_attention() y apply_order_result().

ORDER_NUMBER_PREFIX = "OT"
ORDER_NUMBER_PADDING = 6

# Código del tipo de orden de instalación en el catálogo. Se nombra aquí
# porque es el dominio quien conoce sus propios códigos: apply_order_result()
# ya decide por él, el alta comercial lo necesita para registrar la OT y el
# canal técnico para publicarla. Una sola definición evita que las tres se
# desalineen, y en particular evita confundirlo con el DEMO-INSTALLATION de
# datos de prueba.
INSTALLATION_ORDER_TYPE_CODE = "INSTALLATION"
INCIDENT_ORDER_TYPE_CODE = "INCIDENT"
OUTSIDE_PLANT_ORDER_TYPE_CODE = "OUTSIDE_PLANT"
TRANSFER_ORDER_TYPE_CODE = "TRANSFER"

TRANSFER_BASE_FEES = {
    "INTERNAL": Decimal("20.00"),
    "EXTERNAL": Decimal("30.00"),
}

# Estados de suscripción desde los que NO se admite registrar trabajo nuevo.
SUBSCRIPTION_BLOCKED_STATUSES = (
    Subscription.Status.CANCELLED,
)


def format_order_number(year, number):
    """Formato oficial del correlativo: OT-2026-000001."""
    return f"{ORDER_NUMBER_PREFIX}-{year}-{number:0{ORDER_NUMBER_PADDING}d}"


def generate_order_number(year=None):
    """
    Reserva y devuelve el siguiente número de OT del año.

    Debe ejecutarse dentro de una transacción: bloquea la fila del correlativo
    con select_for_update() y la incrementa. Mientras esa transacción no
    termine, cualquier otro proceso que pida un número del mismo año espera en
    el bloqueo, de modo que jamás se reparte el mismo número dos veces.

    En PostgreSQL (motor de producción) select_for_update() aplica un bloqueo
    real de fila. SQLite ignora la cláusula FOR UPDATE, pero serializa las
    escrituras a nivel de base de datos; además la restricción unique de
    WorkOrder.order_number actúa como última barrera de integridad.
    """
    if year is None:
        year = timezone.localdate().year

    try:
        sequence = WorkOrderSequence.objects.select_for_update().get(year=year)

    except WorkOrderSequence.DoesNotExist:
        # Primer número del año. El savepoint evita que una colisión con otro
        # proceso creando la misma fila invalide la transacción de la orden.
        try:
            with transaction.atomic():
                WorkOrderSequence.objects.create(year=year, last_number=0)

        except IntegrityError:
            pass

        sequence = WorkOrderSequence.objects.select_for_update().get(year=year)

    sequence.last_number += 1

    sequence.save(
        update_fields=[
            "last_number",
            "updated_at",
        ]
    )

    return format_order_number(year, sequence.last_number)


def _resolve_branch(
    subscription,
    branch,
    order_type=None,
    subtype=None,
):
    """Resuelve la sede operativa de la OT.

    Un traslado externo es la excepción deliberada: puede salir de Jauja y
    atenderse en La Oroya/Huancayo, así que su sede de trabajo es la del
    destino, no necesariamente la sede histórica del abonado.
    """
    if subscription is None:
        if branch is None or branch.pk is None:
            raise ValidationError(
                "Las órdenes sin abonado deben indicar una sede."
            )
        return branch

    service_branch = (
        subscription.address.zone.branch
        if subscription.address_id
        and subscription.address.zone_id
        else subscription.customer.branch
    )

    if branch is None:
        return service_branch

    is_external_transfer = (
        order_type is not None
        and order_type.code == TRANSFER_ORDER_TYPE_CODE
        and subtype is not None
        and subtype.code == "EXTERNAL"
    )

    if branch.pk != service_branch.pk and not is_external_transfer:
        raise ValidationError(
            "La sede indicada no corresponde a la sede actual del servicio."
        )

    return branch


def _resolve_zone(subscription, zone, branch):
    """La zona puede venir de la dirección del abonado o directamente en PEX."""
    resolved_zone = zone

    if subscription is not None and resolved_zone is None:
        resolved_zone = subscription.address.zone

    if resolved_zone is None:
        return None

    if resolved_zone.branch_id != branch.pk:
        raise ValidationError(
            "La zona de la orden no pertenece a la sede correspondiente."
        )

    return resolved_zone


def _validate_creation_catalogs(subscription, order_type, subtype, reason, cause):
    if order_type is None or order_type.pk is None:
        raise ValidationError(
            "Debe indicar un tipo de orden registrado."
        )

    if not order_type.is_active:
        raise ValidationError(
            "El tipo de orden seleccionado no está activo."
        )

    if (
        subscription is not None
        and not order_type.applies_to_service_type(subscription.service_type_id)
    ):
        raise ValidationError({
            "order_type": f"«{order_type.name}» no se emite sobre una suscripción {subscription.service_type}."
        })

    if subscription is None and order_type.code != OUTSIDE_PLANT_ORDER_TYPE_CODE:
        raise ValidationError(
            "Solo Planta Externa puede registrarse sin una suscripción."
        )

    if subtype is not None and not subtype.is_active:
        raise ValidationError(
            "El subtipo seleccionado no está activo."
        )

    if reason is not None and not reason.is_active:
        raise ValidationError(
            "El motivo seleccionado no está activo."
        )

    if cause is not None and not cause.is_active:
        raise ValidationError(
            "La causa seleccionada no está activa."
        )

    if subtype is not None and subtype.order_type_id != order_type.pk:
        raise ValidationError(
            "El subtipo seleccionado no pertenece al tipo de orden."
        )

    if reason is not None and reason.order_type_id != order_type.pk:
        raise ValidationError(
            "El motivo seleccionado no pertenece al tipo de orden."
        )

    if cause is not None and cause.order_type_id != order_type.pk:
        raise ValidationError(
            "La causa seleccionada no pertenece al tipo de orden."
        )


def _validate_seller(seller):
    """
    `seller` es opcional -no toda orden nace de una venta con vendedor
    identificado-, pero cuando se envía debe ser un usuario activo con rol
    Ventas: igual que assigned_technician exige rol Técnico en el formulario
    de despacho, aquí se exige rol Ventas para no registrar como vendedor a
    un usuario de otra área.
    """
    if seller is None:
        return

    if seller.pk is None or not seller.is_active:
        raise ValidationError(
            "El vendedor indicado debe ser un usuario activo."
        )

    if seller.role != User.Role.SALES:
        raise ValidationError(
            "El vendedor indicado debe tener el rol de Ventas."
        )


def _validate_creation_subscription(subscription, customer, order_type=None):
    if subscription is None:
        if (
            order_type is not None
            and order_type.code == OUTSIDE_PLANT_ORDER_TYPE_CODE
        ):
            return

        raise ValidationError(
            "Debe indicar una suscripción registrada."
        )

    if subscription.pk is None:
        raise ValidationError(
            "Debe indicar una suscripción registrada."
        )

    if not subscription.is_active:
        raise ValidationError(
            "La suscripción no está habilitada para registrar órdenes."
        )

    if subscription.status in SUBSCRIPTION_BLOCKED_STATUSES:
        raise ValidationError(
            "No puede registrarse trabajo sobre una suscripción cancelada."
        )

    if customer is not None and customer.pk != subscription.customer_id:
        raise ValidationError(
            "La suscripción no corresponde al cliente indicado."
        )


@transaction.atomic
def create_work_order(
    *,
    subscription,
    order_type,
    created_by,
    customer=None,
    branch=None,
    zone=None,
    subtype=None,
    reason=None,
    reason_text="",
    cause=None,
    attention_type=None,
    priority=None,
    detail="",
    scheduled_at=None,
    seller=None,
):
    """
    Registra una nueva orden de trabajo y devuelve la instancia creada.

    Punto de entrada único: valida las reglas de negocio ANTES de persistir,
    reserva el correlativo de forma transaccional y deja la orden en
    Status.PENDING con created_by trazado al usuario ejecutor.

    `created_by` sale siempre del usuario que ejecuta la operación, nunca de
    datos enviados por el cliente. Tampoco se aceptan `order_number` ni
    `assigned_technician`: el número lo emite el correlativo y la asignación
    de técnico es un flujo aparte.

    `seller` es opcional y, si se envía, debe ser un usuario activo con rol
    Ventas (ver `_validate_seller`); registra quién originó la venta que dio
    lugar a la orden, sin abrir un campo de texto libre.

    Crear la orden NO toca la suscripción. Una OT de instalación sobre una
    suscripción en PRESALE la deja en PRESALE.

    Todo ocurre dentro de una única transacción: si cualquier validación o
    escritura falla no queda ni la orden ni el consumo del correlativo.
    """
    if created_by is None or created_by.pk is None:
        raise ValidationError(
            "Debe indicar el usuario que registra la orden."
        )

    if not created_by.is_active:
        raise ValidationError(
            "El usuario que registra la orden debe estar activo."
        )

    _validate_creation_subscription(subscription, customer, order_type)
    _validate_creation_catalogs(subscription, order_type, subtype, reason, cause)
    _validate_seller(seller)

    branch = _resolve_branch(
        subscription,
        branch,
        order_type=order_type,
        subtype=subtype,
    )
    zone = _resolve_zone(subscription, zone, branch)

    order = WorkOrder(
        order_number=generate_order_number(),
        subscription=subscription,
        order_type=order_type,
        subtype=subtype,
        reason=reason,
        reason_text=(reason_text or "").strip(),
        cause=cause,
        branch=branch,
        zone=zone,
        status=WorkOrder.Status.PENDING,
        created_by=created_by,
        detail=detail,
        scheduled_at=scheduled_at,
        seller=seller,
    )

    if attention_type is not None:
        order.attention_type = attention_type

    if priority is not None:
        order.priority = priority

    order.full_clean()
    order.save()

    return order

@transaction.atomic
def create_transfer_work_order(
    *,
    subscription,
    created_by,
    subtype,
    customer=None,
    destination_branch=None,
    destination_zone=None,
    previous_location="",
    new_location="",
    requested_address_text="",
    requested_reference="",
    requested_supply_code="",
    requested_latitude=None,
    requested_longitude=None,
    estimated_extra_amount=Decimal("0.00"),
    customer_agreed_amount=None,
    charge_mode=TransferDetail.ChargeMode.UPFRONT_BASE,
    collection_mode=TransferDetail.CollectionMode.IMMEDIATE,
    attention_type=None,
    priority=None,
    detail="",
    scheduled_at=None,
):
    """Registra un TRASLADO con su estimación y propuesta de cobro.

    La propuesta no es deuda todavía. ATC puede resolverla el mismo día o
    dejarla pendiente según la modalidad elegida. En externo, la sede/zona
    de la OT representan el destino operativo para que llegue a la cuadrilla
    que realmente la atenderá.
    """
    try:
        order_type = OrderType.objects.get(
            code=TRANSFER_ORDER_TYPE_CODE,
            is_active=True,
        )
    except OrderType.DoesNotExist as exc:
        raise ValidationError(
            "El catálogo no contiene un tipo de orden TRASLADO activo."
        ) from exc

    if subtype is None or subtype.order_type_id != order_type.pk:
        raise ValidationError(
            "Debe indicar si el traslado es interno o externo."
        )

    if subtype.code not in TRANSFER_BASE_FEES:
        raise ValidationError("El subtipo de traslado no es válido.")

    try:
        estimated_extra_amount = Decimal(estimated_extra_amount or 0)
    except Exception as exc:
        raise ValidationError("El adicional estimado no es válido.") from exc

    if estimated_extra_amount < 0:
        raise ValidationError("El adicional estimado no puede ser negativo.")

    base_fee = TRANSFER_BASE_FEES[subtype.code]

    valid_charge_modes = {
        value for value, _label in TransferDetail.ChargeMode.choices
    }
    if charge_mode not in valid_charge_modes:
        raise ValidationError("La modalidad de definición del cobro no es válida.")

    valid_collection_modes = {
        value for value, _label in TransferDetail.CollectionMode.choices
    }
    if collection_mode not in valid_collection_modes:
        raise ValidationError("La modalidad de cobro no es válida.")

    if customer_agreed_amount in ("", None):
        if charge_mode == TransferDetail.ChargeMode.UPFRONT_BASE:
            customer_agreed_amount = base_fee
        elif charge_mode == TransferDetail.ChargeMode.UPFRONT_FULL:
            customer_agreed_amount = base_fee + estimated_extra_amount
        else:
            customer_agreed_amount = None
    else:
        try:
            customer_agreed_amount = Decimal(customer_agreed_amount)
        except Exception as exc:
            raise ValidationError(
                "El monto informado al abonado no es válido."
            ) from exc

        if customer_agreed_amount < 0:
            raise ValidationError(
                "El monto informado al abonado no puede ser negativo."
            )

    if subtype.code == "INTERNAL":
        destination_zone = subscription.address.zone
        destination_branch = (
            destination_zone.branch
            if destination_zone is not None
            else subscription.customer.branch
        )
    else:
        if destination_branch is None or destination_branch.pk is None:
            raise ValidationError(
                "Un traslado externo debe indicar la sede destino."
            )
        if destination_zone is None or destination_zone.pk is None:
            raise ValidationError(
                "Un traslado externo debe indicar la zona destino."
            )
        if destination_zone.branch_id != destination_branch.pk:
            raise ValidationError(
                "La zona destino no pertenece a la sede destino."
            )
        if not (requested_address_text or "").strip():
            raise ValidationError(
                "Un traslado externo debe registrar el destino solicitado."
            )

    order = create_work_order(
        subscription=subscription,
        order_type=order_type,
        created_by=created_by,
        customer=customer,
        branch=destination_branch,
        zone=destination_zone,
        subtype=subtype,
        attention_type=attention_type,
        priority=priority,
        detail=detail,
        scheduled_at=scheduled_at,
    )

    transfer = TransferDetail(
        work_order=order,
        previous_address=(
            subscription.address if subtype.code == "EXTERNAL" else None
        ),
        previous_location=(previous_location or "").strip(),
        new_location=(new_location or "").strip(),
        requested_address_text=(requested_address_text or "").strip(),
        requested_reference=(requested_reference or "").strip(),
        requested_supply_code=(requested_supply_code or "").strip(),
        requested_latitude=requested_latitude,
        requested_longitude=requested_longitude,
        base_fee_snapshot=base_fee,
        estimated_extra_amount=estimated_extra_amount,
        customer_agreed_amount=customer_agreed_amount,
        charge_mode=charge_mode,
        collection_mode=collection_mode,
        requires_additional_cabling=estimated_extra_amount > 0,
    )
    transfer.full_clean()
    transfer.save()

    from apps.payments.proposals import propose_transfer_charge
    propose_transfer_charge(work_order=order)

    return order


@transaction.atomic
def confirm_external_transfer_destination(
    *,
    order,
    user,
    address,
    district,
    zone,
    reference="",
    supply_code="",
    latitude=None,
    longitude=None,
):
    """El técnico confirma/corrige el domicilio real de un traslado externo."""
    if (
        order.order_type_id is None
        or order.order_type.code != TRANSFER_ORDER_TYPE_CODE
        or order.subtype_id is None
        or order.subtype.code != "EXTERNAL"
    ):
        raise ValidationError(
            "Solo un traslado externo admite confirmación de nuevo domicilio."
        )

    if order.status not in {
        WorkOrder.Status.IN_PROGRESS,
        WorkOrder.Status.ATTENDED,
    }:
        raise ValidationError(
            "El destino solo puede confirmarse durante o al finalizar la atención."
        )

    if user is None or user.pk is None or not user.is_active:
        raise ValidationError(
            "Debe indicar un técnico activo que confirma el domicilio."
        )

    if order.assigned_technician_id != user.pk:
        raise ValidationError(
            "Solo el técnico que atiende la orden puede confirmar el domicilio."
        )

    if zone is None or zone.pk is None or zone.branch_id != order.branch_id:
        raise ValidationError(
            "La zona confirmada debe pertenecer a la sede destino de la orden."
        )

    address = (address or "").strip()
    district = (district or "").strip()
    if not address or not district:
        raise ValidationError(
            "Debe indicar dirección y distrito del domicilio confirmado."
        )

    if (latitude is None) != (longitude is None):
        raise ValidationError(
            "La ubicación confirmada debe incluir latitud y longitud."
        )

    transfer = TransferDetail.objects.select_for_update().get(work_order=order)

    if transfer.new_address_id:
        destination = transfer.new_address
        destination.zone = zone
        destination.address = address
        destination.reference = (reference or "").strip()
        destination.district = district
        destination.electrical_supply_code = (supply_code or "").strip()
        destination.latitude = latitude
        destination.longitude = longitude
        destination.is_active = True
        destination.full_clean()
        destination.save()
    else:
        destination = CustomerAddress(
            customer=order.subscription.customer,
            zone=zone,
            address=address,
            reference=(reference or "").strip(),
            district=district,
            electrical_supply_code=(supply_code or "").strip(),
            latitude=latitude,
            longitude=longitude,
            is_primary=False,
            is_active=True,
        )
        destination.full_clean()
        destination.save()

    transfer.new_address = destination
    transfer.confirmed_supply_code = (supply_code or "").strip()
    transfer.confirmed_latitude = latitude
    transfer.confirmed_longitude = longitude
    transfer.confirmed_by = user
    transfer.confirmed_at = timezone.now()
    transfer.full_clean()
    transfer.save()

    return transfer


@transaction.atomic
def create_outside_plant_order(
    *,
    created_by,
    branch,
    route,
    reason,
    detail,
    zone=None,
    reference="",
    latitude=None,
    longitude=None,
    priority=None,
    scheduled_at=None,
):
    """Registra una OT PEX independiente de abonados."""

    if created_by is None or created_by.pk is None or not created_by.is_active:
        raise ValidationError(
            "Debe indicar un usuario activo que registre la orden PEX."
        )

    if created_by.role not in (User.Role.ATC, User.Role.NOC):
        raise ValidationError(
            "Las órdenes de Planta Externa solo pueden ser creadas por ATC o NOC."
        )

    if not created_by.has_perm("work_orders.create_outsideplant"):
        raise ValidationError(
            "El usuario no está autorizado para registrar Planta Externa."
        )

    route = (route or "").strip()
    detail = (detail or "").strip()
    reference = (reference or "").strip()

    if len(route) < 3:
        raise ValidationError({"route": "Debe indicar la vía o tramo de trabajo."})

    if len(detail) < 5:
        raise ValidationError({
            "detail": "Debe describir el trabajo o afectación de Planta Externa."
        })

    try:
        order_type = OrderType.objects.get(
            code=OUTSIDE_PLANT_ORDER_TYPE_CODE,
            is_active=True,
        )
    except OrderType.DoesNotExist:
        raise ValidationError(
            "No existe el tipo de orden PLANTA EXTERNA activo."
        )

    if reason is None or reason.pk is None or reason.order_type_id != order_type.pk:
        raise ValidationError(
            "Debe indicar un motivo válido de Planta Externa."
        )

    origin = (
        OutsidePlantDetail.Origin.NOC
        if created_by.role == User.Role.NOC
        else OutsidePlantDetail.Origin.ATC
    )

    order = create_work_order(
        subscription=None,
        order_type=order_type,
        created_by=created_by,
        branch=branch,
        zone=zone,
        reason=reason,
        attention_type=WorkOrder.AttentionType.FIELD,
        priority=priority,
        detail=detail,
        scheduled_at=scheduled_at,
    )

    pex = OutsidePlantDetail(
        work_order=order,
        origin=origin,
        route=route,
        reference=reference,
        latitude=latitude,
        longitude=longitude,
    )
    pex.full_clean(exclude=["work_order"])
    pex.save()

    return order


@transaction.atomic
def create_incident_work_order(
    *,
    subscription,
    created_by,
    reason_text,
    customer=None,
    branch=None,
    zone=None,
    detail="",
):
    """
    Registra una incidencia para atención remota por NOC.

    Una incidencia:
    - siempre pertenece al tipo INCIDENT;
    - siempre es de atención SYSTEM;
    - no se programa;
    - no se asigna a un técnico de campo;
    - exige un motivo escrito por el operador;
    - crea automáticamente su IncidentDetail.

    La operación completa es atómica: si falla la creación del detalle,
    tampoco queda registrada la WorkOrder.
    """
    reason_text = (reason_text or "").strip()

    if len(reason_text) < 3:
        raise ValidationError({
            "reason_text": (
                "Debe indicar el motivo de la incidencia "
                "con al menos 3 caracteres."
            )
        })

    try:
        order_type = OrderType.objects.get(
            code=INCIDENT_ORDER_TYPE_CODE,
            is_active=True,
        )
    except OrderType.DoesNotExist:
        raise ValidationError(
            "No existe el tipo de orden de incidencia activo "
            f"(código «{INCIDENT_ORDER_TYPE_CODE}»)."
        )

    order = create_work_order(
        subscription=subscription,
        order_type=order_type,
        created_by=created_by,
        customer=customer,
        branch=branch,
        zone=zone,
        reason_text=reason_text,
        attention_type=WorkOrder.AttentionType.SYSTEM,
        detail=(detail or "").strip(),
        scheduled_at=None,
    )

    IncidentDetail.objects.create(
        work_order=order,
    )

    return order

INCIDENT_START_PERMISSION = "work_orders.start_incident"
INCIDENT_CLOSE_PERMISSION = "work_orders.close_incident"


def _require_incident_permission(user, permission, action):
    """Valida al operador de NOC mediante permiso funcional, no por rol."""
    if user is None or user.pk is None:
        raise ValidationError(
            f"Debe indicar el usuario que {action}."
        )

    if not user.is_active:
        raise ValidationError(
            f"El usuario que {action} debe estar activo."
        )

    if not user.has_perm(permission):
        raise ValidationError(
            f"El usuario no está autorizado para {action}. "
            f"Requiere el permiso {permission}."
        )


@transaction.atomic
def start_incident_attention(order: WorkOrder, user, remarks=""):
    """
    Inicia formalmente una incidencia NOC.

    El flujo es propio de incidencias:
    PENDING -> IN_PROGRESS.

    No asigna técnico de campo ni utiliza start_attention().
    """
    if order is None or order.pk is None:
        raise ValidationError(
            "Debe indicar una incidencia registrada."
        )

    _require_incident_permission(
        user,
        INCIDENT_START_PERMISSION,
        "inicia la atención de la incidencia",
    )

    try:
        order = (
            WorkOrder.objects
            .select_for_update()
            .select_related("order_type")
            .get(pk=order.pk)
        )
    except WorkOrder.DoesNotExist:
        raise ValidationError(
            "La incidencia indicada ya no existe."
        )

    if not order.is_incident:
        raise ValidationError(
            "La orden indicada no es una incidencia NOC."
        )

    if order.status != WorkOrder.Status.PENDING:
        raise ValidationError(
            "Solo una incidencia pendiente puede iniciar atención. "
            f"Estado actual: {order.get_status_display()}."
        )

    if order.attention_type != WorkOrder.AttentionType.SYSTEM:
        raise ValidationError(
            "La incidencia debe estar registrada como atención de sistema."
        )

    if order.assigned_technician_id is not None:
        raise ValidationError(
            "Una incidencia NOC no puede tener técnico de campo asignado."
        )

    if order.scheduled_at or order.scheduled_date:
        raise ValidationError(
            "Una incidencia NOC no puede tener programación de campo."
        )

    order.started_at = timezone.now()
    order.save(
        update_fields=[
            "started_at",
            "updated_at",
        ]
    )

    order.change_status(
        WorkOrder.Status.IN_PROGRESS,
        user=user,
        remarks=(remarks or "").strip(),
    )

    return order


@transaction.atomic
def close_incident_attention(
    order: WorkOrder,
    user,
    attention_detail,
    observations="",
    remarks="",
):
    """
    Finaliza una incidencia atendida remotamente por NOC.

    IN_PROGRESS -> ATTENDED.

    El detalle de atención es obligatorio. Los datos técnicos restantes
    son opcionales y el usuario responsable se obtiene del ejecutor.
    """
    if order is None or order.pk is None:
        raise ValidationError(
            "Debe indicar una incidencia registrada."
        )

    _require_incident_permission(
        user,
        INCIDENT_CLOSE_PERMISSION,
        "finaliza la incidencia",
    )

    attention_detail = (attention_detail or "").strip()

    if not attention_detail:
        raise ValidationError({
            "attention_detail": (
                "Debe registrar el detalle de atención de la incidencia."
            )
        })

    try:
        order = (
            WorkOrder.objects
            .select_for_update()
            .select_related("order_type")
            .get(pk=order.pk)
        )
    except WorkOrder.DoesNotExist:
        raise ValidationError(
            "La incidencia indicada ya no existe."
        )

    if not order.is_incident:
        raise ValidationError(
            "La orden indicada no es una incidencia NOC."
        )

    if order.status != WorkOrder.Status.IN_PROGRESS:
        raise ValidationError(
            "Solo una incidencia en atención puede finalizarse. "
            f"Estado actual: {order.get_status_display()}."
        )

    try:
        incident_detail = (
            IncidentDetail.objects
            .select_for_update()
            .get(work_order=order)
        )
    except IncidentDetail.DoesNotExist:
        raise ValidationError(
            "La incidencia no cuenta con su detalle NOC asociado."
        )

    incident_detail.attention_detail = attention_detail
    incident_detail.observations = (observations or "").strip()
    incident_detail.attended_by = user

    incident_detail.save(
        update_fields=[
            "attention_detail",
            "observations",
            "attended_by",
            "updated_at",
        ]
    )

    order.change_status(
        WorkOrder.Status.ATTENDED,
        user=user,
        remarks=(remarks or "").strip(),
    )

    return order

def get_subscription_technical_context(subscription, exclude_order=None):
    """
    Devuelve el contexto técnico más reciente conocido de una suscripción.

    La información se consulta desde órdenes físicas previas que tengan
    ficha técnica de campo y/o liquidación. No se copia ni se modifica
    información dentro de la incidencia.

    `exclude_order` permite excluir la incidencia que se está consultando.
    """

    if subscription is None or subscription.pk is None:
        raise ValidationError(
            "Debe indicar una suscripción registrada."
        )

    orders = (
        WorkOrder.objects
        .filter(
            subscription=subscription,
            attention_type=WorkOrder.AttentionType.FIELD,
        )
        .filter(
            models.Q(field_sheet__isnull=False)
            | models.Q(liquidation__isnull=False)
        )
        .select_related(
            "order_type",
            "assigned_technician",
            "field_sheet",
            "field_sheet__updated_by",
            "liquidation",
            "liquidation__liquidated_by",
        )
        .distinct()
    )

    if exclude_order is not None and exclude_order.pk is not None:
        orders = orders.exclude(pk=exclude_order.pk)

    # La OT física más reciente es la mejor representación disponible
    # del estado técnico actual de la suscripción.
    source_order = orders.order_by("-created_at", "-pk").first()

    if source_order is None:
        return None

    try:
        field_sheet = source_order.field_sheet
    except WorkOrder.field_sheet.RelatedObjectDoesNotExist:
        field_sheet = None

    try:
        liquidation = source_order.liquidation
    except WorkOrder.liquidation.RelatedObjectDoesNotExist:
        liquidation = None

    return {
        "source_order": source_order,
        "field_sheet": field_sheet,
        "liquidation": liquidation,

        # Datos de ficha técnica
        "nap": field_sheet.nap if field_sheet else "",
        "terminal": field_sheet.terminal if field_sheet else "",
        "equipment_code": (
            field_sheet.equipment_code if field_sheet else ""
        ),
        "seal_number": (
            field_sheet.seal_number if field_sheet else ""
        ),
        "technician_notes": (
            field_sheet.notes if field_sheet else ""
        ),
        "field_updated_by": (
            field_sheet.updated_by if field_sheet else None
        ),
        "field_updated_at": (
            field_sheet.updated_at if field_sheet else None
        ),

        # Datos de liquidación
        "network_element": (
            liquidation.network_element if liquidation else ""
        ),
        "network_port": (
            liquidation.network_port if liquidation else ""
        ),
        "equipment_serial": (
            liquidation.equipment_serial if liquidation else ""
        ),
        "signal_level_dbm": (
            liquidation.signal_level_dbm if liquidation else None
        ),
        "resolution_detail": (
            liquidation.resolution_detail if liquidation else ""
        ),
        "technical_notes": (
            liquidation.technical_notes if liquidation else ""
        ),
        "liquidated_by": (
            liquidation.liquidated_by if liquidation else None
        ),
        "liquidated_at": (
            liquidation.liquidated_at if liquidation else None
        ),
    }

@transaction.atomic
def create_installation_work_order(
    *,
    subscription,
    created_by,
    customer=None,
    branch=None,
    zone=None,
    reason=None,
    priority=None,
    detail="",
    scheduled_at=None,
    attention_type=None,
    seller=None,
):
    """
    Registra la OT de instalación que produce el alta comercial FTTH.

    Punto de entrada del flujo comercial hacia el dominio de órdenes. Resuelve
    el tipo INSTALLATION y delega la persistencia en create_work_order(), que
    sigue siendo el único camino que emite el correlativo, valida la
    suscripción y persiste la orden.

    La fachada también garantiza idempotencia operativa por suscripción: no se
    permite crear una segunda instalación mientras exista otra que todavía no
    esté en un estado final. Se bloquea la fila de Subscription con
    select_for_update() antes de comprobarlo, de modo que dos solicitudes
    concurrentes para la misma alta no puedan publicar dos órdenes abiertas.

    Una instalación previa en LIQUIDATED, REJECTED, NOT_FEASIBLE o CANCELLED
    no bloquea un nuevo intento; ATTENDED sí bloquea porque aún falta la
    liquidación técnica.

    No se exponen `subtype` —la instalación no tiene subtipos en el catálogo,
    solo corte y traslado los usan— ni `cause`, que se registra durante la
    atención y no al crear la orden.

    `attention_type` (revisión del 03/09): antes la fachada lo fijaba siempre
    a FIELD para evitar que una orden de instalación terminara como
    Sistema/NOC por accidente. Ahora ATC sí puede elegirlo explícitamente
    (Campo / Sistema) al generar la orden desde el resumen de contratación,
    así que se acepta como argumento opcional; si no se envía, se mantiene el
    valor por defecto FIELD -el mismo comportamiento de antes de esta
    revisión-. `create_work_order()` sigue validando que el valor pertenezca
    a `WorkOrder.AttentionType`.

    `seller` es opcional y se valida en create_work_order() (usuario activo
    con rol Ventas).

    `created_by` debe salir del usuario ejecutor (`request.user`), nunca de
    datos enviados por el navegador.
    """
    if subscription is None or subscription.pk is None:
        raise ValidationError(
            "Debe indicar una suscripción registrada."
        )

    try:
        order_type = OrderType.objects.get(
            code=INSTALLATION_ORDER_TYPE_CODE,
        )

    except OrderType.DoesNotExist:
        # Falta de datos maestros, no error del operador. El mensaje nombra el
        # código exacto para que quien administre el catálogo sepa qué crear.
        raise ValidationError(
            "No existe el tipo de orden de instalación en el catálogo "
            f"(código «{INSTALLATION_ORDER_TYPE_CODE}»). "
            "Debe registrarse antes de generar instalaciones."
        )

    try:
        locked_subscription = (
            Subscription.objects
            .select_for_update()
            .select_related("customer__branch", "address__zone")
            .get(pk=subscription.pk)
        )
    except Subscription.DoesNotExist:
        raise ValidationError(
            "La suscripción indicada ya no existe."
        )

    # Se revalida contra la fila bloqueada, no contra una instancia que pudo
    # quedar desactualizada antes de entrar en la transacción.
    _validate_creation_subscription(locked_subscription, customer)

    has_open_installation = (
        locked_subscription.work_orders
        .filter(order_type__code=INSTALLATION_ORDER_TYPE_CODE)
        .exclude(status__in=WorkOrder.FINAL_STATUSES)
        .exists()
    )

    if has_open_installation:
        raise ValidationError(
            "La suscripción ya tiene una orden de instalación abierta. "
            "Finalícela o anúlela antes de generar otra."
        )

    return create_work_order(
        subscription=locked_subscription,
        order_type=order_type,
        created_by=created_by,
        customer=customer,
        branch=branch,
        zone=zone,
        reason=reason,
        attention_type=attention_type or WorkOrder.AttentionType.FIELD,
        priority=priority,
        detail=detail,
        scheduled_at=scheduled_at,
        seller=seller,
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

def _require_signed_contract_for_successful_installation(order, result):
    """Una instalación exitosa solo existe si el abonado aceptó su contrato."""

    if (
        order.order_type.code != INSTALLATION_ORDER_TYPE_CODE
        or result.code != "SUCCESSFUL"
    ):
        return

    from apps.contracts.signatures import (
        contrato_de_la_orden,
        firma_del_contrato,
    )

    contract = contrato_de_la_orden(order)

    if contract is None:
        raise ValidationError(
            "No se puede finalizar la instalación: la suscripción no tiene "
            "un contrato activo asociado."
        )

    signature = firma_del_contrato(contract)

    if signature is None or not signature.signed_pdf:
        raise ValidationError(
            "No se puede finalizar la instalación hasta que el abonado "
            "firme su contrato."
        )


@transaction.atomic
def attend_order(order: WorkOrder, result, user=None, remarks=""):
    """
    Cierra operativamente la atención de una orden.

    Registra el resultado, mueve la orden a ATTENDED por el mecanismo
    oficial de transición y aplica los efectos sobre la suscripción
    delegando en apply_order_result(). Las reglas de negocio no se
    duplican aquí: viven en las funciones _apply_* de este módulo.
    """
    if order.is_incident:
        raise ValidationError(
            "Las incidencias deben finalizarse mediante el flujo "
            "específico de atención NOC."
        )

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

    _require_signed_contract_for_successful_installation(order, result)

    order.result = result
    order.save(update_fields=["result", "updated_at"])

    order.change_status(
        WorkOrder.Status.ATTENDED,
        user=user,
        remarks=remarks,
    )

    if order.assigned_technician_id:
        close_work_order_participation(
            order,
            order.assigned_technician,
            source=WorkOrderParticipation.Source.FIELD,
        )

    apply_order_result(order)

    return order


# --- Ficha técnica de campo (borrador previo a la liquidación) -------------
#
# WorkOrderFieldSheet documenta NAP, borne, MAC/equipo, precinto y las
# observaciones de campo mientras el técnico todavía está trabajando la
# orden -antes de que exista liquidación-. No es una liquidación: no exige
# resolution_detail, no cierra la orden y no transiciona el estado. El
# técnico puede guardarla varias veces mientras la orden sigue abierta.

FIELD_SHEET_EDITABLE_FIELDS = (
    "nap",
    "terminal",
    "equipment_code",
    "seal_number",
    "notes",
)


def _require_assigned_technician(order, user):
    """
    Solo el técnico asignado a la orden puede completar su ficha técnica o
    adjuntar evidencias mientras la atención sigue abierta.

    No se reconsulta el rol del usuario: assign_technician() ya garantiza que
    assigned_technician es siempre un usuario con rol Técnico, así que
    comparar la identidad basta.
    """
    if user is None or user.pk is None:
        raise ValidationError(
            "Debe indicar el usuario que completa la ficha técnica."
        )

    if not user.is_active:
        raise ValidationError(
            "El usuario que completa la ficha técnica debe estar activo."
        )

    if order.assigned_technician_id != user.pk:
        raise ValidationError(
            "Solo el técnico asignado a la orden puede completar su ficha técnica."
        )

    if order.is_closed:
        raise ValidationError(
            "No se puede editar la ficha técnica de una orden cerrada. "
            f"Estado actual: {order.get_status_display()}."
        )


@transaction.atomic
def update_field_sheet(order: WorkOrder, user, **fields):
    """
    Crea o actualiza la ficha técnica de campo de una orden.

    Único camino legítimo para escribir WorkOrderFieldSheet: valida que quien
    escribe es el técnico asignado y que la orden sigue abierta, y rechaza
    cualquier clave que no esté en FIELD_SHEET_EDITABLE_FIELDS antes de tocar
    la base de datos.
    """
    _require_assigned_technician(order, user)

    unknown_fields = set(fields) - set(FIELD_SHEET_EDITABLE_FIELDS)

    if unknown_fields:
        raise ValidationError(
            "Campos no reconocidos en la ficha técnica: "
            f"{', '.join(sorted(unknown_fields))}."
        )

    sheet, _created = WorkOrderFieldSheet.objects.get_or_create(work_order=order)

    for field, value in fields.items():
        setattr(sheet, field, value)

    sheet.updated_by = user

    sheet.full_clean(exclude=["work_order"])
    sheet.save()

    return sheet


@transaction.atomic
def add_work_order_evidence(order: WorkOrder, user, file, description=""):
    """
    Adjunta una evidencia (foto o archivo) a la orden.

    Mismo criterio de autorización que la ficha técnica: solo el técnico
    asignado, y solo mientras la orden sigue abierta. La evidencia se asocia
    directamente a la orden (liquidation=None); si más adelante se liquida,
    esa liquidación es un registro aparte y no reclama esta evidencia
    automáticamente.
    """
    _require_assigned_technician(order, user)

    if not file:
        raise ValidationError(
            "Debe adjuntar un archivo o fotografía."
        )

    evidence = WorkOrderEvidence(
        work_order=order,
        file=file,
        description=description,
        uploaded_by=user,
    )

    evidence.full_clean(exclude=["work_order", "liquidation"])
    evidence.save()

    return evidence


def open_work_order_participation(
    order,
    user,
    *,
    source,
    remarks="",
    recorded_by=None,
):
    """Abre una intervención trazable si no existe una vigente equivalente."""
    if user is None or user.pk is None or not user.is_active:
        raise ValidationError("El participante debe ser un usuario activo.")

    existing = (
        WorkOrderParticipation.objects
        .filter(
            work_order=order,
            user=user,
            source=source,
            ended_at__isnull=True,
        )
        .order_by("-started_at", "-pk")
        .first()
    )
    if existing is not None:
        return existing

    participation = WorkOrderParticipation(
        work_order=order,
        user=user,
        source=source,
        remarks=(remarks or "").strip(),
        recorded_by=recorded_by,
    )
    participation.full_clean(
        exclude=["work_order", "user", "recorded_by"]
    )
    participation.save()
    return participation


def close_work_order_participation(order, user, *, source=None):
    """Cierra las intervenciones activas del usuario en esa orden."""
    queryset = WorkOrderParticipation.objects.filter(
        work_order=order,
        user=user,
        ended_at__isnull=True,
    )
    if source is not None:
        queryset = queryset.filter(source=source)

    now = timezone.now()
    queryset.update(ended_at=now)
    return now


def _validate_declared_field_participant(order, participant):
    from apps.technicians.models import TechnicianProfile

    if participant is None or participant.pk is None or not participant.is_active:
        raise ValidationError("Todos los participantes deben estar activos.")

    if participant.role != User.Role.TECHNICIAN:
        raise ValidationError(
            "Los participantes declarados en una liquidación deben ser técnicos."
        )

    try:
        area = participant.technician_profile.area
    except TechnicianProfile.DoesNotExist:
        area = TechnicianProfile.Area.INTERNAL_NETWORK

    expected = (
        TechnicianProfile.Area.PEX
        if order.is_outside_plant
        else TechnicianProfile.Area.INTERNAL_NETWORK
    )
    if area != expected:
        raise ValidationError(
            "Uno de los participantes no pertenece a la cuadrilla "
            f"{TechnicianProfile.Area(expected).label}."
        )


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
    participant_users=None,
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

    participation_time = timezone.now()
    for participant in participant_users or []:
        _validate_declared_field_participant(order, participant)

        if order.participations.filter(user=participant).exists():
            continue

        participation = WorkOrderParticipation(
            work_order=order,
            user=participant,
            source=WorkOrderParticipation.Source.LIQUIDATION,
            started_at=participation_time,
            ended_at=participation_time,
            remarks="Participante declarado al liquidar la orden.",
            recorded_by=user,
        )
        participation.full_clean(
            exclude=["work_order", "user", "recorded_by"]
        )
        participation.save()

    _finalize_transfer_on_liquidation(order, user)

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

        # El contrato refleja cuándo ese servicio quedó efectivamente activo.
        # Se estampa al instalar con éxito, nunca al registrarlo en oficina.
        from apps.contracts.signatures import contrato_de_la_orden

        contract = contrato_de_la_orden(order)
        if contract is not None:
            contract.last_activation_date = timezone.localdate()
            contract.save(
                update_fields=[
                    "last_activation_date",
                    "updated_at",
                ]
            )

def _apply_cut_result(order, result_code):
    if result_code != "SUCCESSFUL":
        return

    if not order.reason:
        raise ValidationError(
            "Las órdenes de corte deben indicar el motivo del corte."
        )

    try:
        cut_detail = order.cut_detail
    except WorkOrder.cut_detail.RelatedObjectDoesNotExist:
        raise ValidationError(
            "La orden de corte debe tener un detalle de corte."
        )

    cut_detail.full_clean()

    subscription = order.subscription
    reason_code = order.reason.code

    if reason_code in TEMPORARY_CUT_REASONS:
        subscription.status = Subscription.Status.SUSPENDED
        subscription.cut_date = timezone.localdate()

    elif reason_code in DEFINITIVE_CUT_REASONS:
        subscription.status = Subscription.Status.CANCELLED
        subscription.cut_date = timezone.localdate()

    else:
        # Un motivo nuevo en el catálogo no puede cerrar un corte por
        # omisión: decidir si suspende o cancela una suscripción es una
        # regla explícita, no un valor por defecto.
        raise ValidationError(
            f"El motivo «{order.reason.name}» no indica si el corte es "
            "temporal o definitivo."
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
    """Atender un traslado no cambia todavía el domicilio oficial."""
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

    if order.subtype.code not in {"INTERNAL", "EXTERNAL"}:
        raise ValidationError(
            "El subtipo de traslado no es válido."
        )


def _finalize_transfer_on_liquidation(order, user):
    """Aplica el domicilio real solo al liquidar un traslado exitoso."""
    if (
        order.order_type_id is None
        or order.order_type.code != TRANSFER_ORDER_TYPE_CODE
        or order.result_id is None
        or not order.result.is_success
    ):
        return

    transfer = order.transfer_detail

    if order.subtype.code == "INTERNAL":
        return

    if order.subtype.code != "EXTERNAL":
        raise ValidationError("El subtipo de traslado no es válido.")

    if transfer.new_address_id is None:
        raise ValidationError(
            "Antes de liquidar un traslado externo el técnico debe confirmar "
            "el nuevo domicilio."
        )

    if transfer.confirmed_by_id != getattr(user, "pk", None):
        raise ValidationError(
            "El domicilio debe haber sido confirmado por el técnico que "
            "liquida la orden."
        )

    subscription = order.subscription
    subscription.address = transfer.new_address
    subscription.save(update_fields=["address", "updated_at"])
