"""Garantías de idempotencia del alta comercial FTTH."""

from django.core.exceptions import ValidationError

from apps.work_orders.models import WorkOrder
from apps.work_orders.services import create_installation_work_order
from apps.work_orders.tests.base import WorkOrderTestCase


class InstallationUniquenessTests(WorkOrderTestCase):
    """Una suscripción no publica dos instalaciones abiertas a la vez."""

    def create_installation(self):
        return create_installation_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
        )

    def test_second_open_installation_is_rejected(self):
        first = self.create_installation()

        with self.assertRaises(ValidationError) as caught:
            self.create_installation()

        self.assertIn(
            "ya tiene una orden de instalación abierta",
            " ".join(caught.exception.messages),
        )
        self.assertEqual(
            WorkOrder.objects.filter(
                subscription=self.subscription,
                order_type=self.installation_type,
            ).count(),
            1,
        )
        self.assertEqual(
            WorkOrder.objects.get(pk=first.pk).status,
            WorkOrder.Status.PENDING,
        )

    def test_cancelled_installation_allows_a_new_attempt(self):
        first = self.create_installation()
        first.change_status(
            WorkOrder.Status.CANCELLED,
            user=self.atc_user,
            remarks="Reintento autorizado de instalación.",
        )

        second = self.create_installation()

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(second.status, WorkOrder.Status.PENDING)
        self.assertEqual(
            WorkOrder.objects.filter(
                subscription=self.subscription,
                order_type=self.installation_type,
            ).count(),
            2,
        )

    def test_wrapper_sets_field_attention_explicitly(self):
        order = self.create_installation()

        self.assertEqual(
            order.attention_type,
            WorkOrder.AttentionType.FIELD,
        )
