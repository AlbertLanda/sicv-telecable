"""Regresiones del retiro de la asignación manual desde el portal web."""

from django.urls import reverse

from apps.work_orders.models import WorkOrder, WorkOrderAssignment
from apps.work_orders.tests.base import WorkOrderTestCase


class RetiredWebAssignmentTests(WorkOrderTestCase):
    def setUp(self):
        super().setUp()
        self.order = self.create_order()
        self.url = reverse("work_orders:assign", kwargs={"pk": self.order.pk})

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_authenticated_user_sees_retirement_notice(self):
        self.client.login(username="atc1", password="test1234")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 410)
        self.assertContains(
            response,
            "La asignación de órdenes ya no se realiza desde el portal web.",
            status_code=410,
        )

    def test_post_cannot_assign_a_technician(self):
        self.client.login(username="atc1", password="test1234")

        response = self.client.post(
            self.url,
            {
                "assigned_technician": self.technician.pk,
                "status": "ASSIGNED",
            },
        )

        self.assertEqual(response.status_code, 405)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(self.order.assigned_technician_id)
        self.assertFalse(WorkOrderAssignment.objects.filter(work_order=self.order).exists())

    def test_unknown_and_existing_ids_have_same_public_contract(self):
        """El pk no cambia lo observable ni revela si la OT existe.

        No se comparan bytes completos porque el template base incorpora un
        token CSRF distinto en cada respuesta. Lo estable y relevante para no
        enumerar órdenes es el código HTTP y el mismo aviso funcional.
        """
        self.client.login(username="atc1", password="test1234")

        existing = self.client.get(self.url)
        unknown = self.client.get(
            reverse("work_orders:assign", kwargs={"pk": self.order.pk + 9999})
        )

        for response in (existing, unknown):
            self.assertEqual(response.status_code, 410)
            self.assertContains(
                response,
                "La asignación de órdenes ya no se realiza desde el portal web.",
                status_code=410,
            )
            self.assertNotContains(
                response,
                self.order.order_number,
                status_code=410,
            )
