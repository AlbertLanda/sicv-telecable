"""Regresiones del flujo: programar no equivale a asignar técnico."""

from datetime import timedelta

from django.utils import timezone

from apps.work_orders.models import WorkOrder
from apps.work_orders.tests.test_web_schedule_board import ScheduleBoardTestCase


class PendingWorkOrderSchedulingTests(ScheduleBoardTestCase):
    def test_pending_order_is_draggable_on_the_schedule_board(self):
        order = self.create_order()
        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(order.assigned_technician)

        self.login(self.dispatcher)
        response = self.board()

        self.assertIn(
            WorkOrder.Status.PENDING,
            response.context["reschedulable_statuses"],
        )
        self.assertIn(order, self.every_order(response))

    def test_pending_order_can_be_scheduled_without_a_technician(self):
        order = self.create_order()
        target = self.today + timedelta(days=4)

        self.login(self.dispatcher)
        response = self.reschedule(order, target)

        order.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(order.assigned_technician)
        self.assertEqual(
            timezone.localtime(order.scheduled_at).date(),
            target,
        )
        self.assertEqual(order.reprogrammings.count(), 1)
        self.assertEqual(order.status_history.count(), 0)

    def test_pending_order_can_move_to_another_day_and_stay_pending(self):
        original = self.today + timedelta(days=2)
        target = self.today + timedelta(days=5)
        order = self.create_order(
            scheduled_at=self.at(original, hour=16, minute=30),
        )

        self.login(self.dispatcher)
        response = self.reschedule(order, target)
        order.refresh_from_db()

        moved = timezone.localtime(order.scheduled_at)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual((moved.hour, moved.minute), (16, 30))
        self.assertEqual(moved.date(), target)
        self.assertIsNone(order.assigned_technician)

        trace = order.reprogrammings.get()
        self.assertEqual(
            timezone.localtime(trace.previous_schedule).date(),
            original,
        )
        self.assertEqual(
            timezone.localtime(trace.new_schedule).date(),
            target,
        )

    def test_scheduling_pending_order_does_not_make_it_my_order(self):
        """La agenda no debe apropiarse de la OT en nombre del operador."""
        order = self.create_order()

        self.login(self.dispatcher)
        self.reschedule(order, self.today + timedelta(days=3))
        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(order.assigned_technician_id)
        self.assertFalse(order.assignments.exists())
