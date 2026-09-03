from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.work_orders.models import WorkOrder

from .models import SubscriptionAnnexAdjustment


@receiver(post_save, sender=WorkOrder)
def apply_successful_annex_adjustment(sender, instance, **kwargs):
    """
    Aplica el movimiento de anexos cuando la OT llega a LIQUIDATED.

    El receptor es deliberadamente estrecho: ignora todas las demás órdenes,
    órdenes no exitosas y movimientos ya aplicados. La función de dominio
    realiza nuevamente las validaciones y el bloqueo transaccional.
    """
    if instance.status != WorkOrder.Status.LIQUIDATED:
        return

    if not instance.result_id or not instance.result.is_success:
        return

    exists = SubscriptionAnnexAdjustment.objects.filter(
        work_order_id=instance.pk,
        applied_at__isnull=True,
    ).exists()

    if not exists:
        return

    from .annexes import apply_annex_adjustment_from_order

    apply_annex_adjustment_from_order(instance)
