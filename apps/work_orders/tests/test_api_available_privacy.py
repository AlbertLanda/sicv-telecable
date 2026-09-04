"""Minimización de datos en la bandeja compartida del técnico."""

from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.work_orders.tests.base import WorkOrderTestCase


class AvailableOrdersPrivacyTests(WorkOrderTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        token, _ = Token.objects.get_or_create(user=self.technician)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.url = reverse("work_orders_api:available")

    def test_available_customer_exposes_only_code_and_display_name(self):
        self.create_order()

        response = self.api.get(self.url)
        customer = response.data[0]["customer"]

        self.assertEqual(
            set(customer.keys()),
            {"code", "display_name"},
        )
        self.assertNotIn("document_type", customer)
        self.assertNotIn("document_number", customer)

    def test_available_still_does_not_expose_exact_address(self):
        self.create_order()

        row = self.api.get(self.url).data[0]

        for field in (
            "address",
            "reference",
            "latitude",
            "longitude",
            "gps_link",
        ):
            self.assertNotIn(field, row)
