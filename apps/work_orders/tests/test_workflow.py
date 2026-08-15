"""
Pruebas 17 y 18: reprogramación e inicio de atención.

Verifica que la reprogramación conserve la fecha anterior en el histórico y
que start_attention() registre el inicio real usando el mecanismo oficial
de transición.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.work_orders.models import WorkOrder, WorkOrderReprogramming
from apps.work_orders.tests.base import WorkOrderTestCase


class WorkOrderReprogrammingTests(WorkOrderTestCase):

    def test_reprogramming_keeps_previous_schedule(self):
        """17. Reprogramación conserva la fecha anterior."""
        original_schedule = timezone.now() + timedelta(days=1)
        new_schedule = timezone.now() + timedelta(days=3)

        order = self.create_assigned_order(scheduled_at=original_schedule)

        order.reprogram(
            new_schedule=new_schedule,
            user=self.supervisor,
            reason="El cliente no se encontraba en el domicilio",
        )

        order.refresh_from_db()

        record = WorkOrderReprogramming.objects.get(work_order=order)

        self.assertEqual(record.previous_schedule, original_schedule)
        self.assertEqual(record.new_schedule, new_schedule)
        self.assertEqual(record.created_by, self.supervisor)
        self.assertEqual(
            record.reason,
            "El cliente no se encontraba en el domicilio",
        )

        # La orden queda con la nueva fecha, pero el histórico se conserva.
        self.assertEqual(order.scheduled_at, new_schedule)
        self.assertEqual(order.status, WorkOrder.Status.REPROGRAMMED)

    def test_reprogramming_keeps_full_history(self):
        """Complemento: varias reprogramaciones encadenan su histórico."""
        first_schedule = timezone.now() + timedelta(days=1)
        second_schedule = timezone.now() + timedelta(days=2)
        third_schedule = timezone.now() + timedelta(days=5)

        order = self.create_assigned_order(scheduled_at=first_schedule)

        order.reprogram(new_schedule=second_schedule, user=self.supervisor)

        order.assign_technician(
            technician=self.technician,
            assigned_by=self.supervisor,
        )

        order.reprogram(new_schedule=third_schedule, user=self.supervisor)

        order.refresh_from_db()

        self.assertEqual(order.reprogrammings.count(), 2)
        self.assertEqual(order.scheduled_at, third_schedule)

    def test_reprogramming_a_closed_order_is_rejected(self):
        """Complemento: una orden cerrada no se puede reprogramar."""
        order = self.create_order()
        order.change_status(WorkOrder.Status.CANCELLED, user=self.supervisor)

        with self.assertRaises(ValidationError):
            order.reprogram(
                new_schedule=timezone.now() + timedelta(days=2),
                user=self.supervisor,
            )

        self.assertEqual(order.reprogrammings.count(), 0)

    def test_reprogramming_backwards_is_rejected(self):
        """Complemento: la nueva fecha debe ser posterior a la vigente."""
        original_schedule = timezone.now() + timedelta(days=5)

        order = self.create_assigned_order(scheduled_at=original_schedule)

        with self.assertRaises(ValidationError):
            order.reprogram(
                new_schedule=timezone.now() + timedelta(days=1),
                user=self.supervisor,
            )

        order.refresh_from_db()

        self.assertEqual(order.scheduled_at, original_schedule)
        self.assertEqual(order.reprogrammings.count(), 0)


class WorkOrderStartAttentionTests(WorkOrderTestCase):

    def test_start_attention_registers_started_at(self):
        """18. start_attention() registra started_at."""
        order = self.create_assigned_order()

        before = timezone.now()
        order.start_attention(user=self.technician)
        after = timezone.now()

        order.refresh_from_db()

        self.assertIsNotNone(order.started_at)
        self.assertGreaterEqual(order.started_at, before)
        self.assertLessEqual(order.started_at, after)
        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)

    def test_start_attention_leaves_status_trace(self):
        """Complemento: el inicio de atención deja trazabilidad del usuario."""
        order = self.create_assigned_order()

        order.start_attention(user=self.technician, remarks="Llegó al domicilio")

        entry = order.status_history.get(
            new_status=WorkOrder.Status.IN_PROGRESS
        )

        self.assertEqual(entry.previous_status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(entry.changed_by, self.technician)
        self.assertEqual(entry.remarks, "Llegó al domicilio")

    def test_start_attention_from_pending_is_rejected(self):
        """Complemento: no se puede iniciar la atención sin asignar."""
        order = self.create_order()

        with self.assertRaises(ValidationError):
            order.start_attention(user=self.technician)

        order.refresh_from_db()

        self.assertIsNone(order.started_at)
        self.assertEqual(order.status, WorkOrder.Status.PENDING)

    def test_start_attention_on_closed_order_is_rejected(self):
        """Complemento: una orden cerrada no puede iniciar atención."""
        order = self.create_assigned_order()
        order.change_status(WorkOrder.Status.REJECTED, user=self.supervisor)

        with self.assertRaises(ValidationError):
            order.start_attention(user=self.technician)

        order.refresh_from_db()

        self.assertIsNone(order.started_at)
        self.assertTrue(order.is_closed)
