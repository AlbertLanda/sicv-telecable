"""
Pruebas 9 a 14: matriz de transiciones y trazabilidad de estados.

Verifica el flujo principal PENDING -> ASSIGNED -> IN_PROGRESS -> ATTENDED,
el bloqueo de transiciones no permitidas y que cada cambio válido deje
registro en WorkOrderStatusHistory.
"""

from django.core.exceptions import ValidationError

from apps.work_orders.models import WorkOrder, WorkOrderStatusHistory
from apps.work_orders.tests.base import WorkOrderTestCase

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone


class WorkOrderTransitionTests(WorkOrderTestCase):

    def test_pending_to_assigned_is_allowed(self):
        """9. PENDING -> ASSIGNED -> permitido."""
        order = self.create_order()

        changed = order.change_status(
            WorkOrder.Status.ASSIGNED,
            user=self.supervisor,
        )

        order.refresh_from_db()

        self.assertTrue(changed)
        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)

    def test_assigned_to_in_progress_is_allowed(self):
        """10. ASSIGNED -> IN_PROGRESS -> permitido."""
        order = self.create_assigned_order()

        order.change_status(
            WorkOrder.Status.IN_PROGRESS,
            user=self.technician,
        )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)

    def test_in_progress_to_attended_is_allowed(self):
        """11. IN_PROGRESS -> ATTENDED -> permitido."""
        order = self.create_order_in_progress()

        order.change_status(
            WorkOrder.Status.ATTENDED,
            user=self.technician,
        )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.ATTENDED)
        self.assertIsNotNone(order.attended_at)

    def test_pending_to_attended_is_forbidden(self):
        """12. PENDING -> ATTENDED -> prohibido."""
        order = self.create_order()

        with self.assertRaises(ValidationError):
            order.change_status(
                WorkOrder.Status.ATTENDED,
                user=self.technician,
            )

        order.refresh_from_db()

        # Ni la orden ni el historial deben haber cambiado.
        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual(order.status_history.count(), 0)

    def test_cancelled_to_in_progress_is_forbidden(self):
        """13. CANCELLED -> IN_PROGRESS -> prohibido."""
        order = self.create_order()
        order.change_status(WorkOrder.Status.CANCELLED, user=self.supervisor)

        history_before = order.status_history.count()

        with self.assertRaises(ValidationError):
            order.change_status(
                WorkOrder.Status.IN_PROGRESS,
                user=self.technician,
            )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.CANCELLED)
        self.assertEqual(order.status_history.count(), history_before)

    def test_change_status_creates_status_history(self):
        """14. change_status() crea WorkOrderStatusHistory."""
        order = self.create_order()

        order.change_status(
            WorkOrder.Status.ASSIGNED,
            user=self.supervisor,
            remarks="Asignada al turno mañana",
        )

        history = WorkOrderStatusHistory.objects.filter(work_order=order)

        self.assertEqual(history.count(), 1)

        entry = history.first()

        self.assertEqual(entry.previous_status, WorkOrder.Status.PENDING)
        self.assertEqual(entry.new_status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(entry.changed_by, self.supervisor)
        self.assertEqual(entry.remarks, "Asignada al turno mañana")

    def test_full_main_flow_leaves_complete_trace(self):
        """Complemento: el flujo principal deja una traza completa."""
        order = self.create_order()

        order.change_status(WorkOrder.Status.ASSIGNED, user=self.supervisor)
        order.change_status(WorkOrder.Status.IN_PROGRESS, user=self.technician)
        order.change_status(WorkOrder.Status.ATTENDED, user=self.technician)

        transitions = list(
            order.status_history.order_by("id").values_list(
                "previous_status", "new_status"
            )
        )

        self.assertEqual(
            transitions,
            [
                (WorkOrder.Status.PENDING, WorkOrder.Status.ASSIGNED),
                (WorkOrder.Status.ASSIGNED, WorkOrder.Status.IN_PROGRESS),
                (WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.ATTENDED),
            ],
        )

    def test_terminal_statuses_have_no_exits(self):
        """Complemento: los estados terminales no admiten salidas."""
        for status in WorkOrder.TERMINAL_STATUSES:
            self.assertEqual(
                WorkOrder.ALLOWED_TRANSITIONS[status],
                [],
                f"El estado {status} no debería admitir transiciones.",
            )

    def test_invalid_status_value_is_rejected(self):
        """Complemento: un estado inexistente es rechazado."""
        order = self.create_order()

        with self.assertRaises(ValidationError):
            order.change_status("NO_EXISTE", user=self.supervisor)

        self.assertEqual(order.status_history.count(), 0)

    def test_same_status_does_not_create_history(self):
        """Complemento: repetir el estado actual es una operación nula."""
        order = self.create_order()

        changed = order.change_status(
            WorkOrder.Status.PENDING,
            user=self.supervisor,
        )

        self.assertFalse(changed)
        self.assertEqual(order.status_history.count(), 0)

    def test_reprogrammed_to_in_progress_is_allowed(self):
        """REPROGRAMMED -> IN_PROGRESS -> permitido."""
        order = self.create_assigned_order()

        order.reprogram(
            new_schedule=timezone.now() + timedelta(days=2),
            user=self.supervisor,
            reason="Cliente solicita nueva fecha",
        )

        order.start_attention(
            user=self.technician,
            remarks="Atención retomada en fecha reprogramada",
        )

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            WorkOrder.Status.IN_PROGRESS,
        )
