"""
Pruebas del endpoint «Mis órdenes» de la API del técnico.

Cubren aislamiento por técnico, permisos, forma de respuesta, orden de agenda
y ausencia de N+1. La API distingue fecha+hora de día-sin-hora porque ambas
son compromisos reales que el técnico debe poder leer en campo.
"""

from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.work_orders.tests.base import WorkOrderTestCase


class MyWorkOrdersAPITestCase(WorkOrderTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("work_orders_api:my_orders")
        self.api = APIClient()

    def authenticate(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return token

    def order_numbers(self, response):
        return [row["order_number"] for row in response.data]


class MyWorkOrdersListTests(MyWorkOrdersAPITestCase):
    def test_technician_sees_only_own_orders(self):
        own = self.create_assigned_order()

        other = self.create_order()
        other.assign_technician(
            technician=self.other_technician,
            assigned_by=self.supervisor,
        )
        unassigned = self.create_order()

        self.authenticate(self.technician)
        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.order_numbers(response), [own.order_number])
        self.assertNotIn(other.order_number, self.order_numbers(response))
        self.assertNotIn(unassigned.order_number, self.order_numbers(response))

    def test_technician_without_orders_gets_empty_list(self):
        order = self.create_order()
        order.assign_technician(
            technician=self.other_technician,
            assigned_by=self.supervisor,
        )

        self.authenticate(self.technician)
        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_response_exposes_the_agreed_fields(self):
        order = self.create_assigned_order()
        self.authenticate(self.technician)
        row = self.api.get(self.url).data[0]

        self.assertEqual(
            set(row.keys()),
            {
                "id",
                "order_number",
                "customer",
                "service_type",
                "plan",
                "order_type",
                "subtype",
                "status",
                "status_display",
                "priority",
                "priority_display",
                "scheduled_at",
                "scheduled_date",
                "agenda_date",
                "created_at",
            },
        )

        self.assertEqual(row["order_number"], order.order_number)
        self.assertEqual(row["status"], order.status)
        self.assertEqual(row["status_display"], "Asignada")
        self.assertEqual(row["order_type"], "Instalación")
        self.assertEqual(row["service_type"], "Internet")
        self.assertIsNone(row["scheduled_date"])
        self.assertIsNone(row["agenda_date"])

        self.assertEqual(
            set(row["customer"].keys()),
            {"code", "document_type", "document_number", "display_name"},
        )
        self.assertEqual(row["customer"]["code"], "CLI001")
        self.assertEqual(row["customer"]["display_name"], "Juan Pérez Ramos")

    def test_day_only_schedule_is_exposed_without_inventing_a_time(self):
        target = timezone.localdate() + timedelta(days=2)
        order = self.create_assigned_order(scheduled_date=target)

        self.authenticate(self.technician)
        response = self.api.get(self.url)
        row = next(item for item in response.data if item["id"] == order.pk)

        self.assertIsNone(row["scheduled_at"])
        self.assertEqual(row["scheduled_date"], target.isoformat())
        self.assertEqual(row["agenda_date"], target.isoformat())

    def test_datetime_schedule_keeps_its_agenda_day(self):
        scheduled_at = timezone.now() + timedelta(days=2, hours=3)
        order = self.create_assigned_order(scheduled_at=scheduled_at)

        self.authenticate(self.technician)
        response = self.api.get(self.url)
        row = next(item for item in response.data if item["id"] == order.pk)

        self.assertIsNotNone(row["scheduled_at"])
        self.assertIsNone(row["scheduled_date"])
        self.assertEqual(
            row["agenda_date"],
            timezone.localtime(scheduled_at).date().isoformat(),
        )

    def test_orders_are_sorted_by_schedule_with_nulls_last(self):
        now = timezone.now()
        later = self.create_assigned_order(
            scheduled_at=now + timedelta(hours=5),
        )
        sooner = self.create_assigned_order(
            scheduled_at=now + timedelta(hours=1),
        )
        unscheduled = self.create_assigned_order()

        self.authenticate(self.technician)
        response = self.api.get(self.url)

        self.assertEqual(
            self.order_numbers(response),
            [
                sooner.order_number,
                later.order_number,
                unscheduled.order_number,
            ],
        )


class MyWorkOrdersPermissionTests(MyWorkOrdersAPITestCase):
    def test_request_without_token_is_rejected(self):
        response = self.api.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_non_technician_is_rejected(self):
        self.authenticate(self.atc_user)
        response = self.api.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_deactivated_technician_with_live_token_is_rejected(self):
        self.authenticate(self.technician)
        self.assertEqual(self.api.get(self.url).status_code, 200)

        self.technician.is_active = False
        self.technician.save(update_fields=["is_active"])

        response = self.api.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_technician_moved_to_another_role_loses_access(self):
        self.authenticate(self.technician)
        self.assertEqual(self.api.get(self.url).status_code, 200)

        self.technician.role = self.technician.Role.ATC
        self.technician.save(update_fields=["role"])

        response = self.api.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class MyWorkOrdersQueryCountTests(MyWorkOrdersAPITestCase):
    def test_query_count_does_not_grow_with_the_number_of_orders(self):
        self.authenticate(self.technician)
        self.create_assigned_order()

        with CaptureQueriesContext(connection) as baseline:
            self.api.get(self.url)

        for _ in range(6):
            self.create_assigned_order()

        with self.assertNumQueries(len(baseline.captured_queries)):
            response = self.api.get(self.url)

        self.assertEqual(len(response.data), 7)
