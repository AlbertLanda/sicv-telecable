"""Regresiones de contratos de entrada y escrituras con una OT desactualizada."""

import json
import sqlite3
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import OperationalError
from django.test import Client
from django.urls import resolve, Resolver404
from django.utils import timezone

from apps.work_orders.models import WorkOrder
from apps.work_orders.services import attend_order
from apps.work_orders.tests.base import WorkOrderTestCase
from apps.work_orders.tests.test_web_schedule_board import ScheduleBoardTestCase


class ScheduleInputSafetyTests(ScheduleBoardTestCase):
    def test_impossible_and_extreme_week_dates_do_not_crash(self):
        self.login(self.viewer)
        for value in ("2026-02-30", "2026-13-01", "0001-01-01", "9999-12-31"):
            with self.subTest(value=value):
                response = self.board(fecha=value)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["is_current_week"])

    def test_invalid_json_shapes_and_dates_never_change_the_order(self):
        order = self.create_assigned_order()
        before = order.status_history.count()
        self.login(self.dispatcher)
        values = [[], None, 1, "date", {"date": "2026-02-30"},
                  {"date": "9999-12-31"}, {"date": ["2026-09-07"]}]
        for value in values:
            with self.subTest(value=value):
                response = self.client.post(
                    self.reschedule_url(order), json.dumps(value),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(order.reprogrammings.count(), 0)
        self.assertEqual(order.status_history.count(), before)

    def test_today_is_available_and_a_later_hour_is_accepted(self):
        now = self.at(self.today, hour=8)
        order = self.create_assigned_order(
            scheduled_at=self.at(self.today + timedelta(days=1), hour=15),
        )
        self.login(self.dispatcher)
        with patch("django.utils.timezone.now", return_value=now):
            response = self.board()
            today_column = next(c for c in response.context["day_columns"]
                                if c["date"] == self.today)
            self.assertTrue(today_column["is_droppable"])
            self.assertEqual(self.reschedule(order, self.today).status_code, 200)
        order.refresh_from_db()
        self.assertEqual(timezone.localtime(order.scheduled_at), self.at(self.today, hour=15))

    def test_today_with_an_elapsed_hour_is_rejected(self):
        order = self.create_assigned_order(
            scheduled_at=self.at(self.today + timedelta(days=1), hour=9),
        )
        self.login(self.dispatcher)
        with patch("django.utils.timezone.now", return_value=self.at(self.today, hour=15)):
            self.assertEqual(self.reschedule(order, self.today).status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)

    def test_atc_consults_without_dragging_or_dispatch_actions(self):
        self.create_assigned_order(scheduled_at=None)
        self.login(self.viewer)
        response = self.board()
        self.assertContains(response, "Solo lectura")
        self.assertNotContains(response, 'draggable="true"')
        self.assertNotContains(response, "/assign/")
        with self.assertRaises(Resolver404):
            resolve("/work-orders/dispatch/")

    def test_reschedule_requires_csrf_even_with_permission(self):
        order = self.create_assigned_order()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.dispatcher)
        response = client.post(
            self.reschedule_url(order),
            json.dumps({"date": (self.today + timedelta(days=1)).isoformat()}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(order.reprogrammings.count(), 0)

    def test_response_refreshes_global_stats_for_the_displayed_week(self):
        self.create_assigned_order(scheduled_at=None)
        order = self.create_assigned_order(scheduled_at=self.at(self.today - timedelta(days=1)))
        target = self.week_start + timedelta(weeks=2)
        self.login(self.dispatcher)
        response = self.client.post(
            self.reschedule_url(order) + "?fecha=" + target.isoformat(),
            json.dumps({"date": target.isoformat()}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stats"], {
            "unscheduled": 1, "overdue": 0, "unassigned": 0, "week": 1,
        })

    def test_an_unscheduled_order_updates_stats_and_keeps_its_technician(self):
        order = self.create_assigned_order(scheduled_at=None)
        self.login(self.dispatcher)
        target = self.week_start + timedelta(weeks=1)
        response = self.client.post(
            self.reschedule_url(order) + "?fecha=" + target.isoformat(),
            json.dumps({"date": target.isoformat()}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stats"]["unscheduled"], 0)
        self.assertEqual(response.json()["stats"]["week"], 1)
        order.refresh_from_db()
        self.assertEqual(order.assigned_technician_id, self.technician.pk)
        self.assertTrue(order.can_start_attention)

    def test_stale_endpoint_read_is_rejected_without_changing_attended_order(self):
        order = self.create_order_in_progress()
        stale = WorkOrder.objects.get(pk=order.pk)
        attend_order(order, self.installation_success, user=self.technician)
        self.login(self.dispatcher)
        with patch("apps.work_orders.views.get_object_or_404", return_value=stale):
            response = self.reschedule(order, self.today + timedelta(days=2))
        self.assertEqual(response.status_code, 400)
        self.assertIn("cambió", response.json()["message"])
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.ATTENDED)
        self.assertEqual(order.reprogrammings.count(), 0)

    def test_sqlite_write_conflict_is_reported_without_a_partial_change(self):
        order = self.create_assigned_order()
        self.login(self.dispatcher)
        cause = sqlite3.OperationalError("database is locked")
        cause.sqlite_errorcode = sqlite3.SQLITE_BUSY
        error = OperationalError("database is locked")
        error.__cause__ = cause
        with patch.object(WorkOrder, "reprogram", side_effect=error):
            response = self.reschedule(order, self.today + timedelta(days=1))
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["ok"])
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(order.reprogrammings.count(), 0)

    def test_unrelated_database_errors_are_not_misreported_as_conflicts(self):
        order = self.create_assigned_order()
        self.login(self.dispatcher)
        with patch.object(WorkOrder, "reprogram", side_effect=OperationalError("disk I/O error")):
            with self.assertRaises(OperationalError):
                self.reschedule(order, self.today + timedelta(days=1))


class ScheduleConcurrentStateTests(WorkOrderTestCase):
    """Dos instancias simulan peticiones que leyeron la misma versión de la OT.

    Se prueban ambos órdenes de escritura; también funcionan sobre SQLite,
    donde select_for_update no ofrece bloqueo por fila.
    """

    def test_stale_reprogramming_cannot_reopen_an_attended_order(self):
        order = self.create_order_in_progress()
        stale = WorkOrder.objects.get(pk=order.pk)
        attend_order(order, self.installation_success, user=self.technician)
        before = order.status_history.count()
        with self.assertRaises(ValidationError):
            stale.reprogram(timezone.now() + timedelta(days=2), user=self.supervisor)
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.ATTENDED)
        self.assertIsNone(order.scheduled_at)
        self.assertEqual(order.reprogrammings.count(), 0)
        self.assertEqual(order.status_history.count(), before)

    def test_stale_completion_cannot_finish_a_reprogrammed_order(self):
        order = self.create_order_in_progress()
        stale = WorkOrder.objects.get(pk=order.pk)
        target = timezone.now() + timedelta(days=2)
        order.reprogram(target, user=self.supervisor)
        before = order.status_history.count()
        with self.assertRaises(ValidationError):
            attend_order(stale, self.installation_success, user=self.technician)
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.REPROGRAMMED)
        self.assertIsNone(order.result_id)
        self.assertIsNone(order.attended_at)
        self.assertEqual(order.status_history.count(), before)

    def test_only_one_of_two_stale_reprogrammings_is_committed(self):
        order = self.create_assigned_order()
        stale = WorkOrder.objects.get(pk=order.pk)
        target = timezone.now() + timedelta(days=2)
        order.reprogram(target, user=self.supervisor)
        with self.assertRaises(ValidationError):
            stale.reprogram(target + timedelta(days=1), user=self.supervisor)
        order.refresh_from_db()
        self.assertEqual(order.scheduled_at, target)
        self.assertEqual(order.reprogrammings.count(), 1)
