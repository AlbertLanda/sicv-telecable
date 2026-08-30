from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User


class ProfileViewTests(TestCase):
    """
    Mi perfil: identidad de solo lectura, contacto editable.

    El foco de estas pruebas es de seguridad, no de formato: verificar
    que ningún valor enviado por el cliente distinto de phone/email
    puede cambiar identidad ni rol, y que la vista siempre opera sobre
    el propio usuario autenticado.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="tecnico1",
            password="ClaveSegura123",
            role=User.Role.TECHNICIAN,
            email="viejo@telecable.pe",
        )
        self.other_user = User.objects.create_user(
            username="tecnico2",
            password="ClaveSegura123",
            role=User.Role.TECHNICIAN,
        )
        self.client.login(username="tecnico1", password="ClaveSegura123")
        self.url = reverse("accounts:profile")

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.headers["Location"])

    def test_profile_page_shows_the_authenticated_users_own_data(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tecnico1")
        self.assertNotContains(response, "tecnico2")

    def test_contact_fields_are_updated(self):
        response = self.client.post(self.url, {
            "phone": "987654321",
            "email": "nuevo@telecable.pe",
        })

        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "987654321")
        self.assertEqual(self.user.email, "nuevo@telecable.pe")

    def test_identity_fields_cannot_be_changed_through_a_manipulated_post(self):
        response = self.client.post(self.url, {
            "phone": "987654321",
            "email": "nuevo@telecable.pe",
            "username": "otro_nombre",
            "role": User.Role.ADMIN,
            "is_superuser": "on",
        })

        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "tecnico1")
        self.assertEqual(self.user.role, User.Role.TECHNICIAN)
        self.assertFalse(self.user.is_superuser)

    def test_profile_always_operates_on_the_authenticated_user(self):
        """
        No hay parámetro de OT ni de pk en esta URL: no existe forma de
        pedir el perfil de otro usuario. Esta prueba fija ese contrato.
        """
        response = self.client.post(self.url, {
            "phone": "000",
            "email": "atacante@telecable.pe",
        })

        self.assertEqual(response.status_code, 302)

        self.other_user.refresh_from_db()
        self.assertNotEqual(self.other_user.email, "atacante@telecable.pe")


class PasswordChangeViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="tecnico1",
            password="ClaveVieja123",
            role=User.Role.TECHNICIAN,
        )
        self.client.login(username="tecnico1", password="ClaveVieja123")
        self.url = reverse("accounts:password_change")

    def test_password_change_page_loads(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_wrong_current_password_is_rejected(self):
        response = self.client.post(self.url, {
            "old_password": "ClaveIncorrecta",
            "new_password1": "ClaveNuevaSegura123",
            "new_password2": "ClaveNuevaSegura123",
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("old_password"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("ClaveVieja123"))

    def test_valid_password_change_redirects_and_updates_the_password(self):
        response = self.client.post(self.url, {
            "old_password": "ClaveVieja123",
            "new_password1": "ClaveNuevaSegura123",
            "new_password2": "ClaveNuevaSegura123",
        })

        self.assertRedirects(response, reverse("accounts:password_change_done"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("ClaveNuevaSegura123"))

    def test_mismatched_new_passwords_are_rejected(self):
        response = self.client.post(self.url, {
            "old_password": "ClaveVieja123",
            "new_password1": "ClaveNuevaSegura123",
            "new_password2": "OtraClaveDistinta123",
        })

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("ClaveVieja123"))
