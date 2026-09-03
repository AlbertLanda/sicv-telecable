from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.organization.models import Branch

from apps.customers.services.document_lookup import (
    DocumentLookupError,
    consultar_documento,
)
from apps.customers.services.jsonpe import (
    JsonPeError,
    consultar_dni,
    consultar_ruc,
)


User = get_user_model()

@override_settings(
    JSONPE_API_TOKEN="token-falso-para-tests",
    JSONPE_API_BASE_URL="https://api.json.pe/api",
    JSONPE_API_TIMEOUT=8,
)
class JsonPeProviderTests(SimpleTestCase):
    """
    Pruebas del adaptador JSON.pe.

    Ninguna prueba realiza llamadas reales a Internet.
    """

    @patch("apps.customers.services.jsonpe.requests.post")
    def test_consultar_dni_mapea_respuesta_jsonpe(self, mock_post):
        response = Mock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = {
            "success": True,
            "message": "exito",
            "data": {
                "numero": "12345678",
                "nombre_completo": "PEREZ GOMEZ, JUAN CARLOS",
                "nombres": "JUAN CARLOS",
                "apellido_paterno": "PEREZ",
                "apellido_materno": "GOMEZ",
                "codigo_verificacion": 1,
            },
        }

        mock_post.return_value = response

        result = consultar_dni("12345678")

        self.assertEqual(
            result,
            {
                "first_name": "JUAN CARLOS",
                "paternal_surname": "PEREZ",
                "maternal_surname": "GOMEZ",
            },
        )

        mock_post.assert_called_once()

        _, kwargs = mock_post.call_args

        self.assertEqual(
            kwargs["json"],
            {"dni": "12345678"},
        )

        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer token-falso-para-tests",
        )

    @patch("apps.customers.services.jsonpe.requests.post")
    def test_consultar_ruc_mapea_respuesta_jsonpe(self, mock_post):
        response = Mock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = {
            "success": True,
            "message": "exito",
            "data": {
                "numero": "20123456789",
                "nombre_o_razon_social": "EMPRESA PRUEBA SAC",
                "estado": "ACTIVO",
                "condicion": "HABIDO",
                "direccion": "JR. PRUEBA 123",
            },
        }

        mock_post.return_value = response

        result = consultar_ruc("20123456789")

        self.assertEqual(
            result["business_name"],
            "EMPRESA PRUEBA SAC",
        )
        self.assertEqual(result["status"], "ACTIVO")
        self.assertEqual(result["condition"], "HABIDO")
        self.assertEqual(result["address"], "JR. PRUEBA 123")

        _, kwargs = mock_post.call_args

        self.assertEqual(
            kwargs["json"],
            {"ruc": "20123456789"},
        )

    @patch("apps.customers.services.jsonpe.requests.post")
    def test_dni_invalido_no_consume_api(self, mock_post):
        with self.assertRaises(JsonPeError) as context:
            consultar_dni("123")

        self.assertIn(
            "8 dígitos",
            context.exception.message,
        )

        mock_post.assert_not_called()

    @patch("apps.customers.services.jsonpe.requests.post")
    def test_ruc_invalido_no_consume_api(self, mock_post):
        with self.assertRaises(JsonPeError) as context:
            consultar_ruc("20123")

        self.assertIn(
            "11 dígitos",
            context.exception.message,
        )

        mock_post.assert_not_called()

    @patch("apps.customers.services.jsonpe.requests.post")
    def test_token_rechazado_se_traduce_a_error_controlado(
        self,
        mock_post,
    ):
        response = Mock()
        response.status_code = 401
        response.ok = False

        mock_post.return_value = response

        with self.assertRaises(JsonPeError) as context:
            consultar_dni("12345678")

        self.assertEqual(
            context.exception.status_code,
            502,
        )

        self.assertIn(
            "credenciales",
            context.exception.message.lower(),
        )

    @patch("apps.customers.services.jsonpe.requests.post")
    def test_limite_de_consultas_se_traduce_a_error_controlado(
        self,
        mock_post,
    ):
        response = Mock()
        response.status_code = 429
        response.ok = False

        mock_post.return_value = response

        with self.assertRaises(JsonPeError) as context:
            consultar_dni("12345678")

        self.assertEqual(
            context.exception.status_code,
            502,
        )

        self.assertIn(
            "límite",
            context.exception.message.lower(),
        )

    @patch(
        "apps.customers.services.jsonpe.requests.post",
        side_effect=requests.RequestException("sin conexión"),
    )
    def test_error_de_red_no_rompe_el_flujo(
        self,
        mock_post,
    ):
        with self.assertRaises(JsonPeError) as context:
            consultar_dni("12345678")

        self.assertEqual(
            context.exception.status_code,
            502,
        )

        self.assertIn(
            "conectarse",
            context.exception.message.lower(),
        )


@override_settings(
    JSONPE_API_TOKEN="token-falso-para-tests",
    JSONPE_API_BASE_URL="https://api.json.pe/api",
    JSONPE_API_TIMEOUT=8,
)
class DocumentLookupFacadeTests(SimpleTestCase):

    @patch(
        "apps.customers.services.document_lookup."
        "jsonpe_consultar_dni"
    )
    def test_fachada_envia_dni_a_jsonpe(self, mock_dni):
        mock_dni.return_value = {
            "first_name": "JUAN",
            "paternal_surname": "PEREZ",
            "maternal_surname": "GOMEZ",
        }

        result = consultar_documento(
            "DNI",
            "12345678",
        )

        mock_dni.assert_called_once_with("12345678")
        self.assertEqual(result["first_name"], "JUAN")

    @patch(
        "apps.customers.services.document_lookup."
        "jsonpe_consultar_ruc"
    )
    def test_fachada_envia_ruc_a_jsonpe(self, mock_ruc):
        mock_ruc.return_value = {
            "business_name": "EMPRESA PRUEBA SAC",
        }

        result = consultar_documento(
            "RUC",
            "20123456789",
        )

        mock_ruc.assert_called_once_with("20123456789")

        self.assertEqual(
            result["business_name"],
            "EMPRESA PRUEBA SAC",
        )

    def test_ce_continua_con_registro_manual(self):
        with self.assertRaises(DocumentLookupError) as context:
            consultar_documento(
                "CE",
                "001234567",
            )

        self.assertEqual(
            context.exception.status_code,
            400,
        )

        self.assertIn(
            "manual",
            context.exception.message.lower(),
        )

class CustomerDocumentLookupViewTests(TestCase):

    def setUp(self):
        self.branch = Branch.objects.create(
            code="TST",
            name="Sede Test",
        )

        self.user = User.objects.create_user(
            username="atc_jsonpe_test",
            password="test-password",
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.client.force_login(self.user)

        self.url = reverse(
            "customers:lookup_document"
        )

    @patch(
        "apps.customers.views.consultar_documento"
    )
    def test_endpoint_dni_devuelve_datos_para_autocompletar(
        self,
        mock_consultar,
    ):
        mock_consultar.return_value = {
            "first_name": "JUAN CARLOS",
            "paternal_surname": "PEREZ",
            "maternal_surname": "GOMEZ",
        }

        response = self.client.get(
            self.url,
            {
                "document_type": "DNI",
                "document_number": "12345678",
            },
        )

        self.assertEqual(response.status_code, 200)

        payload = response.json()

        self.assertTrue(payload["ok"])

        self.assertEqual(
            payload["data"]["first_name"],
            "JUAN CARLOS",
        )

        self.assertEqual(
            payload["data"]["paternal_surname"],
            "PEREZ",
        )

        self.assertEqual(
            payload["data"]["maternal_surname"],
            "GOMEZ",
        )

        mock_consultar.assert_called_once_with(
            "DNI",
            "12345678",
        )

    @patch(
        "apps.customers.views.consultar_documento"
    )
    def test_endpoint_traduce_error_del_proveedor(
        self,
        mock_consultar,
    ):
        mock_consultar.side_effect = DocumentLookupError(
            "Servicio temporalmente no disponible.",
            status_code=502,
        )

        response = self.client.get(
            self.url,
            {
                "document_type": "DNI",
                "document_number": "12345678",
            },
        )

        self.assertEqual(response.status_code, 502)

        payload = response.json()

        self.assertFalse(payload["ok"])

        self.assertEqual(
            payload["message"],
            "Servicio temporalmente no disponible.",
        )

    def test_endpoint_requiere_usuario_autenticado(self):
        self.client.logout()

        response = self.client.get(
            self.url,
            {
                "document_type": "DNI",
                "document_number": "12345678",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            "/accounts/login/",
            response.url,
        )