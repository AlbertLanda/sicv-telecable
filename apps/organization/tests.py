from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch


class ActiveBranchTests(TestCase):
    """
    Sede activa: desde qué sede se consulta, no a qué sede pertenece el
    operador.

    La regla de negocio que fijan estas pruebas es que un ATC de Huancayo
    puede atender a un abonado de Oroya sin derivar la llamada, y que
    hacerlo no cambia su asignación.
    """

    def setUp(self):
        self.huancayo = Branch.objects.create(code="HYO", name="Huancayo")
        self.oroya = Branch.objects.create(code="ORO", name="Oroya")
        self.inactiva = Branch.objects.create(
            code="OLD",
            name="Sede cerrada",
            is_active=False,
        )

        self.user = User.objects.create_user(
            username="atc1",
            password="ClaveSegura123",
            role=User.Role.ATC,
            branch=self.huancayo,
        )
        self.client.login(username="atc1", password="ClaveSegura123")
        self.url = reverse("organization:set_active_branch")

    def test_active_branch_defaults_to_the_users_own_branch(self):
        response = self.client.get(reverse("customers:search"))

        self.assertEqual(response.context["active_branch"], self.huancayo)

    def test_operator_can_switch_to_another_branch(self):
        self.client.post(self.url, {"branch": self.oroya.pk})

        response = self.client.get(reverse("customers:search"))

        self.assertEqual(response.context["active_branch"], self.oroya)

    def test_switching_branch_does_not_change_the_users_assignment(self):
        self.client.post(self.url, {"branch": self.oroya.pk})

        self.user.refresh_from_db()
        self.assertEqual(self.user.branch, self.huancayo)

    def test_inactive_branch_is_rejected(self):
        response = self.client.post(self.url, {"branch": self.inactiva.pk})

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(ACTIVE_BRANCH_SESSION_KEY, self.client.session)

    def test_unknown_branch_is_rejected(self):
        response = self.client.post(self.url, {"branch": 999999})

        self.assertEqual(response.status_code, 404)

    def test_get_is_not_allowed(self):
        """Cambiar el ámbito de consulta no debe ocurrir por una visita."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

    def test_anonymous_user_cannot_switch_branch(self):
        self.client.logout()

        response = self.client.post(self.url, {"branch": self.oroya.pk})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.headers["Location"])

    def test_external_next_is_not_followed(self):
        """El formulario no debe servir de trampolín a otro dominio."""
        response = self.client.post(self.url, {
            "branch": self.oroya.pk,
            "next": "https://sitio-externo.example.com/",
        })

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("sitio-externo", response.headers["Location"])

    def test_internal_next_is_followed(self):
        destination = reverse("accounts:profile")

        response = self.client.post(self.url, {
            "branch": self.oroya.pk,
            "next": destination,
        })

        self.assertRedirects(response, destination)
