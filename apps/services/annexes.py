from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Subscription, SubscriptionAnnexAdjustment


TV_ANNEX_ORDER_TYPE_CODE = "TV_ANNEX"


@transaction.atomic
def create_annex_adjustment_work_order(
    *,
    subscription,
    operation,
    quantity,
    created_by,
    detail="",
    priority=None,
    scheduled_at=None,
):
    """
    Crea una OT independiente para aumentar o retirar anexos de TV.

    Crear la OT NO cambia todavía `subscription.annex_count`. El movimiento
    se guarda como snapshot en SubscriptionAnnexAdjustment y solo se aplica
    cuando la misma OT llega a LIQUIDATED con un resultado exitoso.
    """
    from apps.work_orders.models import OrderSubtype, OrderType, WorkOrder
    from apps.work_orders.services import create_work_order

    if subscription is None or subscription.pk is None:
        raise ValidationError("Debe indicar una suscripción registrada.")

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise ValidationError("La cantidad de anexos debe ser un número entero.")

    if quantity < 1:
        raise ValidationError("La cantidad de anexos debe ser mayor a cero.")

    valid_operations = {
        SubscriptionAnnexAdjustment.Operation.ADD,
        SubscriptionAnnexAdjustment.Operation.REMOVE,
    }

    if operation not in valid_operations:
        raise ValidationError("La operación de anexos indicada no es válida.")

    locked_subscription = (
        Subscription.objects
        .select_for_update()
        .select_related(
            "customer__branch",
            "address__zone",
            "service_type",
            "plan",
        )
        .get(pk=subscription.pk)
    )

    if not locked_subscription.is_active:
        raise ValidationError("La suscripción no está habilitada.")

    if locked_subscription.status != Subscription.Status.ACTIVE:
        raise ValidationError(
            "Los anexos futuros solo pueden modificarse sobre una suscripción activa."
        )

    if not locked_subscription.service_type.supports_tv_annexes:
        raise ValidationError(
            "El servicio seleccionado no permite anexos de televisión."
        )

    has_open_adjustment = (
        locked_subscription.work_orders
        .filter(order_type__code=TV_ANNEX_ORDER_TYPE_CODE)
        .exclude(status__in=WorkOrder.FINAL_STATUSES)
        .exists()
    )

    if has_open_adjustment:
        raise ValidationError(
            "La suscripción ya tiene una orden de anexos abierta. "
            "Finalícela o anúlela antes de registrar otra."
        )

    previous_count = locked_subscription.annex_count

    if operation == SubscriptionAnnexAdjustment.Operation.ADD:
        target_count = previous_count + quantity
        installation_charge = (
            Decimal(quantity)
            * locked_subscription.service_type.annex_installation_price
        )
        monthly_delta = (
            Decimal(quantity)
            * locked_subscription.service_type.annex_monthly_price
        )
        subtype_code = "ADD"

    else:
        if quantity > previous_count:
            raise ValidationError(
                "No se pueden retirar más anexos de los que tiene el cliente."
            )

        target_count = previous_count - quantity
        installation_charge = Decimal("0.00")
        monthly_delta = -(
            Decimal(quantity)
            * locked_subscription.service_type.annex_monthly_price
        )
        subtype_code = "REMOVE"

    try:
        order_type = OrderType.objects.get(
            code=TV_ANNEX_ORDER_TYPE_CODE,
            is_active=True,
        )
        subtype = OrderSubtype.objects.get(
            order_type=order_type,
            code=subtype_code,
            is_active=True,
        )
    except (OrderType.DoesNotExist, OrderSubtype.DoesNotExist):
        raise ValidationError(
            "No está configurado el catálogo operativo de anexos de TV."
        )

    order = create_work_order(
        subscription=locked_subscription,
        order_type=order_type,
        subtype=subtype,
        created_by=created_by,
        attention_type=WorkOrder.AttentionType.FIELD,
        priority=priority,
        detail=detail,
        scheduled_at=scheduled_at,
    )

    adjustment = SubscriptionAnnexAdjustment(
        subscription=locked_subscription,
        work_order=order,
        operation=operation,
        previous_annex_count=previous_count,
        quantity=quantity,
        target_annex_count=target_count,
        installation_charge=installation_charge,
        monthly_delta=monthly_delta,
        monthly_charge_after=(
            Decimal(target_count)
            * locked_subscription.service_type.annex_monthly_price
        ),
    )

    adjustment.full_clean()
    adjustment.save()

    return order


@transaction.atomic
def apply_annex_adjustment_from_order(order):
    """
    Aplica el nuevo total de anexos después de una OT liquidada con éxito.

    Es idempotente: una OT aplicada no vuelve a modificar la suscripción.
    También verifica que el total vigente siga siendo el snapshot con el que
    nació la orden, evitando pisar otro movimiento concurrente.
    """
    from apps.work_orders.models import WorkOrder

    if order.status != WorkOrder.Status.LIQUIDATED:
        raise ValidationError(
            "El ajuste de anexos solo puede aplicarse después de liquidar la OT."
        )

    if not order.result or not order.result.is_success:
        return None

    try:
        adjustment = (
            SubscriptionAnnexAdjustment.objects
            .select_for_update()
            .select_related("subscription__service_type")
            .get(work_order=order)
        )
    except SubscriptionAnnexAdjustment.DoesNotExist:
        return None

    if adjustment.applied_at is not None:
        return adjustment

    subscription = (
        Subscription.objects
        .select_for_update()
        .get(pk=adjustment.subscription_id)
    )

    if subscription.annex_count != adjustment.previous_annex_count:
        raise ValidationError(
            "El total de anexos cambió desde que se creó la OT. "
            "Revise la secuencia de órdenes antes de aplicar este movimiento."
        )

    subscription.annex_count = adjustment.target_annex_count
    subscription.full_clean()
    subscription.save(
        update_fields=[
            "annex_count",
            "updated_at",
        ]
    )

    adjustment.applied_at = timezone.now()
    adjustment.save(update_fields=["applied_at"])

    return adjustment
