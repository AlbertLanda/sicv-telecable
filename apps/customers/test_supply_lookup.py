"""Pruebas de consulta de suministro eléctrico y ubicación Distriluz."""

from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.customers.services.distriluz import SupplyLookupError
from apps.customers.services.distriluz_gps import consultar_suministro_gps
from apps.organization.models import Branch


User = get_user_model()


SOAP_WITH_GPS = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ConsultaGeneralResponse xmlns="http://www.distriluz.com.pe/">
      <ConsultaGeneralResult>
        <string>Direccion</string><string>JR PRUEBA 123</string>
        <string>DireccionComplementaria</string><string>SAUSA</string>
        <string>Provincia</string><string>JAUJA</string>
        <string>Departamento</string><string>JUNIN</string>
        <string>GPSY</string><string>-11.7861026</string>
        <string>GPSX</string><string>-75.4900202</string>
        <string>Nombre</string><string>TITULAR NO NECESARIO</string>
        <string>Documento</string><string>00000000</string>
      </ConsultaGeneralResult>
    </ConsultaGeneralResponse>
  </soap:Body>
</soap:Envelope>
"""

SOAP_WITHOUT_GPS = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ConsultaGeneralResponse xmlns="http://www.distriluz.com.pe/">
      <ConsultaGeneralResult>
        <string>Direccion</string><string>JR SIN GPS 456</string>
        <string>DireccionComplementaria</string><string>JAUJA</string>
      </ConsultaGeneralResult>
    </ConsultaGeneralResponse>
  </soap:Body>
</soap:Envelope>
"""

SOAP_WITH_ZERO_GPS = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ConsultaGeneralResponse xmlns="http://www.distriluz.com.pe/">
      <ConsultaGeneralResult>
        <string>Direccion</string><string>JR SIN GEO 789</string>
        <string>DireccionComplementaria</string><string>JAUJA</string>
        <string>GPSY</string><string>0.0000000</string>
        <string>GPSX</string><string>0</string>
      </ConsultaGeneralResult>
    </ConsultaGeneralResponse>
  </soap:Body>
</soap:Envelope>
"""


class DistriluzGPSServiceTests(TestCase):
    @patch("apps.customers.services.distriluz_gps.requests.post")
    def test_returns_only_location_data_with_exact_coordinates(self, post):
        response = Mock(ok=True, text=SOAP_WITH_GPS)
        post.return_value = response

        data = consultar_suministro_gps("75018907")

        self.assertEqual(
            set(data.keys()),
            {
                "supply_code",
                "address",
                "district",
                "province",
                "department",
                "latitude",
                "longitude",
                "gps_link",
            },
        )
        self.assertEqual(data["supply_code"], "75018907")
        self.assertEqual(data["address"], "JR PRUEBA 123")
        self.assertEqual(data["district"], "SAUSA")
        self.assertEqual(data["latitude"], Decimal("-11.7861026"))
        self.assertEqual(data["longitude"], Decimal("-75.4900202"))
        self.assertIn("-11.7861026,-75.4900202", data["gps_link"])
        self.assertNotIn("titular_name", data)
        self.assertNotIn("document_number", data)

    @patch("apps.customers.services.distriluz_gps.requests.post")
    def test_missing_gps_never_invents_coordinates(self, post):
        post.return_value = Mock(ok=True, text=SOAP_WITHOUT_GPS)

        data = consultar_suministro_gps("75018907")

        self.assertEqual(data["address"], "JR SIN GPS 456")
        self.assertIsNone(data["latitude"])
        self.assertIsNone(data["longitude"])
        self.assertEqual(data["gps_link"], "")

    @patch("apps.customers.services.distriluz_gps.requests.post")
    def test_zero_gps_is_normalized_before_it_reaches_the_form(self, post):
        """El centinela 0/0.0000000 de Distriluz nunca entra como GPS válido."""
        post.return_value = Mock(ok=True, text=SOAP_WITH_ZERO_GPS)

        data = consultar_suministro_gps("75018907")

        self.assertIsNone(data["latitude"])
        self.assertIsNone(data["longitude"])
        self.assertEqual(data["gps_link"], "")

    def test_empty_supply_code_is_rejected_without_network_call(self):
        with self.assertRaises(SupplyLookupError) as caught:
            consultar_suministro_gps("")

        self.assertEqual(caught.exception.status_code, 400)

    def test_non_numeric_supply_code_is_rejected_without_network_call(self):
        with self.assertRaises(SupplyLookupError) as caught:
            consultar_suministro_gps("ABC123")

        self.assertEqual(caught.exception.status_code, 400)

    @patch("apps.customers.services.distriluz_gps.requests.post")
    def test_timeout_is_reported_as_controlled_gateway_error(self, post):
        post.side_effect = requests.Timeout()

        with self.assertRaises(SupplyLookupError) as caught:
            consultar_suministro_gps("75018907")

        self.assertEqual(caught.exception.status_code, 502)

    @patch("apps.customers.services.distriluz_gps.requests.post")
    def test_invalid_xml_is_reported_as_controlled_gateway_error(self, post):
        post.return_value = Mock(ok=True, text="<xml-invalido")

        with self.assertRaises(SupplyLookupError) as caught:
            consultar_suministro_gps("75018907")

        self.assertEqual(caught.exception.status_code, 502)

    @patch("apps.customers.services.distriluz_gps.requests.post")
    def test_missing_address_is_not_treated_as_success(self, post):
        post.return_value = Mock(
            ok=True,
            text=(
                '<?xml version="1.0"?>'
                '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                '<soap:Body><ConsultaGeneralResponse xmlns="http://www.distriluz.com.pe/">'
                '<ConsultaGeneralResult><string>GPSY</string><string>-11</string>'
                '</ConsultaGeneralResult></ConsultaGeneralResponse></soap:Body>'
                '</soap:Envelope>'
            ),
        )

        with self.assertRaises(SupplyLookupError) as caught:
            consultar_suministro_gps("75018907")

        self.assertEqual(caught.exception.status_code, 404)


class SupplyLookupViewTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="HYO", name="Huancayo")
        self.user = User.objects.create_user(
            username="atc_supply",
            password="test1234",
            role=User.Role.ATC,
            branch=self.branch,
        )
        self.url = reverse("customers:lookup_supply")

    def test_anonymous_user_cannot_query_supply(self):
        response = self.client.get(self.url, {"supply_number": "75018907"})

        self.assertEqual(response.status_code, 302)

    @patch("apps.customers.views.consultar_suministro_gps")
    def test_authenticated_lookup_returns_normalized_location(self, lookup):
        lookup.return_value = {
            "supply_code": "75018907",
            "address": "JR PRUEBA 123",
            "district": "SAUSA",
            "province": "JAUJA",
            "department": "JUNIN",
            "latitude": "-11.7861026",
            "longitude": "-75.4900202",
            "gps_link": "https://www.google.com/maps/search/?api=1&query=-11.7861026,-75.4900202",
        }
        self.client.login(username="atc_supply", password="test1234")

        response = self.client.get(self.url, {"supply_number": "75018907"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["data"], lookup.return_value)
        lookup.assert_called_once_with("75018907")

    @patch("apps.customers.views.consultar_suministro_gps")
    def test_controlled_lookup_error_keeps_json_contract(self, lookup):
        lookup.side_effect = SupplyLookupError(
            "No se encontró información para el suministro.",
            status_code=404,
        )
        self.client.login(username="atc_supply", password="test1234")

        response = self.client.get(self.url, {"supply_number": "75018907"})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["ok"])
        self.assertIn("message", response.json())
