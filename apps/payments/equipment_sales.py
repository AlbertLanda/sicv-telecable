"""Venta de equipos al abonado con deuda inmediata y OT de instalación."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.services.models import Subscription
from apps.work_orders.models import OrderReason, OrderType, WorkOrder
from apps.work_orders.services import create_work_order

from .models import ChargeConcept, EquipmentProduct, EquipmentSale
from .services import create_manual_charge


REQUIREMENT_ORDER_TYPE_CODE = "REQUIREMENT"
INTERNET_SERVICE_CODES = ("INTERNET", "DUO")


@transaction.atomic
def create_equipment_sale(*, customer, subscription, product, user):
    """Registra venta, deuda y OT de instalación como una sola operación."""

    if user is None or user.pk is None or not user.is_active:
        raise ValidationError(
            "Debe indicar un usuario activo que registre la venta."
        )

    if customer is None or customer.pk is None or not customer.is_active:
        raise ValidationError("El abonado debe estar activo.")

    try:
        locked_subscription = (
            Subscription.objects
            .select_for_update()
            .select_related("customer", "service_type", "address")
            .get(
                pk=subscription.pk,
                customer=customer,
                is_active=True,
                status=Subscription.Status.ACTIVE,
                service_type__code__in=INTERNET_SERVICE_CODES,
            )
        )
    except Subscription.DoesNotExist as exc:
        raise ValidationError(
            "La venta de repetidor o Mesh requiere una suscripción activa "
            "de Internet o Dúo del abonado."
        ) from exc

    try:
        locked_product = (
            EquipmentProduct.objects
            .select_for_update()
            .get(pk=product.pk, is_active=True)
        )
    except EquipmentProduct.DoesNotExist as exc:
        raise ValidationError(
            "El equipo seleccionado ya no está disponible para venta."
        ) from exc

    if locked_product.current_price <= 0:
        raise ValidationError(
            "El equipo no tiene un precio de venta válido."
        )

    try:
        concept = ChargeConcept.objects.get(
            code=locked_product.charge_concept_code,
            is_active=True,
        )
    except ChargeConcept.DoesNotExist as exc:
        raise ValidationError(
            "El catálogo de cobranza no contiene el concepto del equipo."
        ) from exc

    try:
        order_type = OrderType.objects.get(
            code=REQUIREMENT_ORDER_TYPE_CODE,
            is_active=True,
        )
        reason = OrderReason.objects.get(
            order_type=order_type,
            code=locked_product.order_reason_code,
            is_active=True,
        )
    except (OrderType.DoesNotExist, OrderReason.DoesNotExist) as exc:
        raise ValidationError(
            "El catálogo de órdenes no contiene la instalación del equipo."
        ) from exc

    price = locked_product.current_price

    charge = create_manual_charge(
        customer=customer,
        subscription=locked_subscription,
        concept=concept.family,
        concept_item=concept,
        description=f"VENTA {locked_product.name}",
        amount=price,
        due_date=timezone.localdate(),
        auto_update=False,
    )

    work_order = create_work_order(
        subscription=locked_subscription,
        order_type=order_type,
        reason=reason,
        created_by=user,
        customer=customer,
        attention_type=WorkOrder.AttentionType.FIELD,
        priority=WorkOrder.Priority.NORMAL,
        detail=(
            f"Instalar {locked_product.name} adquirido por el abonado. "
            "El monto de venta se gestiona únicamente en cobranza."
        ),
    )

    sale = EquipmentSale(
        customer=customer,
        subscription=locked_subscription,
        product=locked_product,
        price_snapshot=price,
        charge=charge,
        work_order=work_order,
        registered_by=user,
    )
    sale.full_clean()
    sale.save()

    return sale
