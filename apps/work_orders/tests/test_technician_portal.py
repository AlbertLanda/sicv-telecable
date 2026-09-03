from django.test import TestCase
from django.urls import reverse


class TechnicianPortalShellTests(TestCase):
    """El portal es solo un shell; la seguridad de datos vive en la API token."""

    def test_portal_is_reachable_without_web_session(self):
        response = self.client.get(reverse("technician_portal:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Portal del técnico")
        self.assertContains(response, "Órdenes disponibles")
        self.assertContains(response, "Mis órdenes")

    def test_portal_points_to_the_token_api_not_the_web_session(self):
        response = self.client.get(reverse("technician_portal:home"))

        self.assertContains(response, "/api/technicians/login/")
        self.assertContains(response, "/api/technicians/me/")
        self.assertContains(response, "/api/technicians/work-orders/")

    def test_portal_contains_field_workflow_controls(self):
        response = self.client.get(reverse("technician_portal:home"))

        self.assertContains(response, "Ficha técnica")
        self.assertContains(response, "Caja NAP")
        self.assertContains(response, "Borne")
        self.assertContains(response, "MAC / Equipo")
        self.assertContains(response, "Fotos y archivos")

    def test_portal_keeps_textual_address_and_maps_action_visible(self):
        response = self.client.get(reverse("technician_portal:home"))

        self.assertContains(response, "Dirección")
        self.assertContains(response, "Referencia")
        self.assertContains(response, "Abrir en Google Maps")
