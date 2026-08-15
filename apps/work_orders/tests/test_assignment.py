"""
Pruebas 7, 8, 15 y 16: asignación y reasignación de técnicos.

Verifica las validaciones de rol y estado, la creación del historial y la
conservación de la trazabilidad del técnico anterior en una reasignación.
"""

from django.core.exceptions import ValidationError

from apps.work_orders.models import WorkOrder, WorkOrderAssignment
from apps.work_orders.tests.base import WorkOrderTestCase


class WorkOrderAssignmentTests(WorkOrderTestCase):

    def test_assign_technician_role_is_allowed(self):
        """7. Asignación de usuario TECHNICIAN -> permitida."""
        order = self.create_order()

        order.assign_technician(
            technician=self.technician,
            assigned_by=self.supervisor,
            remarks="Asignación inicial",
        )

        order.refresh_from_db()

        self.assertEqual(order.assigned_technician, self.technician)
        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)

    def test_assign_non_technician_role_is_rejected(self):
        """8. Asignación de usuario ATC u otro rol -> ValidationError."""
        order = self.create_order()

        with self.assertRaises(ValidationError):
            order.assign_technician(
                technician=self.atc_user,
                assigned_by=self.supervisor,
            )

        order.refresh_from_db()

        self.assertIsNone(order.assigned_technician)
        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual(order.assignments.count(), 0)

    def test_assign_inactive_technician_is_rejected(self):
        """Complemento: el técnico debe estar activo."""
        order = self.create_order()

        with self.assertRaises(ValidationError):
            order.assign_technician(
                technician=self.inactive_technician,
                assigned_by=self.supervisor,
            )

        self.assertEqual(order.assignments.count(), 0)

    def test_assign_to_cancelled_order_is_rejected(self):
        """Complemento: una orden anulada no admite asignación."""
        order = self.create_order()
        order.change_status(WorkOrder.Status.CANCELLED, user=self.supervisor)

        with self.assertRaises(ValidationError):
            order.assign_technician(
                technician=self.technician,
                assigned_by=self.supervisor,
            )

        self.assertEqual(order.assignments.count(), 0)

    def test_assignment_creates_history(self):
        """15. Asignación crea historial de asignación."""
        order = self.create_order()

        order.assign_technician(
            technician=self.technician,
            assigned_by=self.supervisor,
            remarks="Primera visita",
        )

        assignments = WorkOrderAssignment.objects.filter(work_order=order)

        self.assertEqual(assignments.count(), 1)

        assignment = assignments.first()

        self.assertEqual(assignment.technician, self.technician)
        self.assertEqual(assignment.assigned_by, self.supervisor)
        self.assertEqual(assignment.remarks, "Primera visita")
        self.assertIsNotNone(assignment.assigned_at)
        self.assertIsNone(assignment.unassigned_at)
        self.assertTrue(assignment.is_active)

    def test_reassignment_keeps_previous_technician(self):
        """16. Reasignación conserva el técnico anterior."""
        order = self.create_order()

        order.assign_technician(
            technician=self.technician,
            assigned_by=self.supervisor,
        )

        order.assign_technician(
            technician=self.other_technician,
            assigned_by=self.supervisor,
            remarks="Reasignado por carga de trabajo",
        )

        order.refresh_from_db()

        self.assertEqual(order.assigned_technician, self.other_technician)
        self.assertEqual(order.assignments.count(), 2)

        previous = order.assignments.get(technician=self.technician)
        current = order.assignments.get(technician=self.other_technician)

        # El técnico anterior sigue en el historial, con su cierre registrado.
        self.assertIsNotNone(previous.unassigned_at)
        self.assertFalse(previous.is_active)

        self.assertIsNone(current.unassigned_at)
        self.assertTrue(current.is_active)

    def test_reassignment_keeps_single_active_assignment(self):
        """Complemento: solo una asignación queda vigente a la vez."""
        order = self.create_order()

        order.assign_technician(technician=self.technician)
        order.assign_technician(technician=self.other_technician)
        order.assign_technician(technician=self.technician)

        active = order.assignments.filter(unassigned_at__isnull=True)

        self.assertEqual(order.assignments.count(), 3)
        self.assertEqual(active.count(), 1)
        self.assertEqual(active.first().technician, self.technician)
