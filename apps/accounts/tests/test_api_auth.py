"""
Pruebas de la autenticación por token del canal de API del técnico.

Cubren los siete escenarios mínimos de la actividad: credenciales válidas,
credenciales inválidas, usuario válido sin rol técnico, técnico inactivo, y el
endpoint protegido con y sin token.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from apps.organization.models import Branch

User = get_user_model()

PASSWORD = "test1234"


class TechnicianAuthAPITestCase(APITestCase):
    """Escenario base: un técnico activo, un inactivo y un usuario ATC."""

    def setUp(self):
        self.branch = Branch.objects.create(code="SED01", name="Sede Central")

        self.technician = User.objects.create_user(
            username="tecnico1",
            password=PASSWORD,
            first_name="Luis",
            last_name="Quispe",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
        )

        self.inactive_technician = User.objects.create_user(
            username="tecnico2",
            password=PASSWORD,
            role=User.Role.TECHNICIAN,
            branch=self.branch,
            is_active=False,
        )

        # Mismo branch y misma contraseña que el técnico: aísla el rol como
        # única causa del rechazo interno, sin exponerlo al cliente anónimo.
        self.atc_user = User.objects.create_user(
            username="atc1",
            password=PASSWORD,
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.login_url = reverse("technicians_api:login")
        self.me_url = reverse("technicians_api:me")

    def login(self, username, password=PASSWORD):
        return self.client.post(
            self.login_url,
            {"username": username, "password": password},
            format="json",
        )


class TechnicianLoginTests(TechnicianAuthAPITestCase):
    """Escenarios 1 a 4: emisión del token."""

    def test_valid_technician_receives_token(self):
        """1. Credenciales válidas de técnico -> 200 y token devuelto."""
        response = self.login("tecnico1")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        token = Token.objects.get(user=self.technician)
        self.assertEqual(response.data["token"], token.key)

        # El token identifica: la respuesta trae la identidad del técnico.
        self.assertEqual(response.data["technician"]["username"], "tecnico1")
        self.assertEqual(response.data["technician"]["full_name"], "Luis Quispe")
        self.assertEqual(
            response.data["technician"]["role"],
            User.Role.TECHNICIAN,
        )
        self.assertEqual(
            response.data["technician"]["branch_name"],
            "Sede Central",
        )

    def test_response_never_echoes_the_password(self):
        """La contraseña no vuelve en ninguna forma en la respuesta."""
        response = self.login("tecnico1")

        self.assertNotIn("password", response.data)
        self.assertNotIn("password", response.data["technician"])
        self.assertNotIn(PASSWORD, response.content.decode())

    def test_repeated_login_returns_the_same_token(self):
        """Volver a autenticarse no invalida la sesión activa de la app."""
        first = self.login("tecnico1")
        second = self.login("tecnico1")

        self.assertEqual(first.data["token"], second.data["token"])
        self.assertEqual(Token.objects.filter(user=self.technician).count(), 1)

    def test_invalid_password_is_rejected(self):
        """2. Credenciales inválidas -> 401, sin token."""
        response = self.login("tecnico1", password="incorrecta")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["detail"], "Credenciales inválidas.")
        self.assertNotIn("token", response.data)
        self.assertFalse(Token.objects.filter(user=self.technician).exists())

    def test_unknown_user_is_rejected(self):
        """2b. Usuario inexistente -> 401, con el mismo mensaje genérico."""
        response = self.login("noexiste")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["detail"], "Credenciales inválidas.")
        self.assertNotIn("token", response.data)

    def test_non_technician_is_rejected_without_revealing_valid_password(self):
        """3. Usuario válido no técnico -> 401 genérico, sin token.

        El endpoint público no debe confirmar que el usuario existe ni que la
        contraseña ingresada era correcta. La diferencia de rol permanece en
        el dominio, pero no en la respuesta de autenticación.
        """
        response = self.login("atc1")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["detail"], "Credenciales inválidas.")
        self.assertNotIn("token", response.data)
        self.assertFalse(Token.objects.filter(user=self.atc_user).exists())

    def test_inactive_technician_is_rejected(self):
        """4. Técnico inactivo -> rechazado, aunque la contraseña sea correcta."""
        response = self.login("tecnico2")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["detail"], "Credenciales inválidas.")
        self.assertNotIn("token", response.data)
        self.assertFalse(
            Token.objects.filter(user=self.inactive_technician).exists()
        )

    def test_rejected_login_cases_are_indistinguishable_publicly(self):
        """Password malo, usuario inexistente y rol incorrecto responden igual."""
        wrong_password = self.login("tecnico1", password="incorrecta")
        unknown_user = self.login("noexiste")
        wrong_role = self.login("atc1")

        for response in (wrong_password, unknown_user, wrong_role):
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(response.data, {"detail": "Credenciales inválidas."})

    def test_missing_fields_are_rejected(self):
        """Petición incompleta -> 400, sin llegar a autenticar."""
        response = self.client.post(self.login_url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", response.data)
        self.assertIn("password", response.data)


class ProtectedEndpointTests(TechnicianAuthAPITestCase):
    """Escenarios 5 y 6: el endpoint protegido de referencia."""

    def test_protected_endpoint_without_token_is_rejected(self):
        """5. Endpoint protegido sin token -> 401."""
        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_protected_endpoint_with_invalid_token_is_rejected(self):
        """5b. Token inexistente -> 401."""
        self.client.credentials(HTTP_AUTHORIZATION="Token noesuntoken")

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_protected_endpoint_with_valid_token_is_allowed(self):
        """6. Endpoint protegido con token válido -> 200."""
        token = self.login("tecnico1").data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "tecnico1")
        self.assertEqual(response.data["id"], self.technician.pk)

    def test_web_session_does_not_authenticate_the_api(self):
        """Los dos canales están separados: la sesión web no vale en la API."""
        self.client.force_login(self.technician)

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class DefaultSecurityTests(TechnicianAuthAPITestCase):
    """Los ajustes globales cierran la API por defecto."""

    def test_default_permission_is_authenticated(self):
        from django.conf import settings

        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"],
            ["rest_framework.permissions.IsAuthenticated"],
        )

    def test_default_authentication_is_token_only(self):
        from django.conf import settings

        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"],
            ["rest_framework.authentication.TokenAuthentication"],
        )
