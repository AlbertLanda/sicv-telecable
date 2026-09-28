from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent


class ProfileViewTests(TestCase):
    """El propio usuario mantiene su identidad/contacto, no sus permisos."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="tecnico1",
            password="ClaveSegura123",
            first_name="Técnico",
            last_name="Uno",
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

    def profile_payload(self, **overrides):
        payload = {
            "username": self.user.username,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "phone": self.user.phone,
            "email": self.user.email,
        }
        payload.update(overrides)
        return payload

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

    def test_identity_and_contact_fields_are_updated(self):
        response = self.client.post(
            self.url,
            self.profile_payload(
                username="tecnico.uno",
                first_name="Kevin",
                last_name="Rivera",
                phone="987654321",
                email="nuevo@telecable.pe",
            ),
        )

        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "tecnico.uno")
        self.assertEqual(self.user.first_name, "Kevin")
        self.assertEqual(self.user.last_name, "Rivera")
        self.assertEqual(self.user.phone, "987654321")
        self.assertEqual(self.user.email, "nuevo@telecable.pe")

    def test_privilege_fields_cannot_be_changed_through_a_manipulated_post(self):
        response = self.client.post(
            self.url,
            self.profile_payload(
                role=User.Role.ADMIN,
                is_superuser="on",
                is_staff="on",
                branch="999",
                office="999",
            ),
        )

        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.TECHNICIAN)
        self.assertFalse(self.user.is_superuser)
        self.assertFalse(self.user.is_staff)
        self.assertIsNone(self.user.branch_id)
        self.assertIsNone(self.user.office_id)

    def test_profile_always_operates_on_the_authenticated_user(self):
        response = self.client.post(
            self.url,
            self.profile_payload(
                phone="000",
                email="atacante@telecable.pe",
            ),
        )

        self.assertEqual(response.status_code, 302)

        self.other_user.refresh_from_db()
        self.assertNotEqual(self.other_user.email, "atacante@telecable.pe")

    def test_profile_changes_are_audited_with_before_and_after_values(self):
        response = self.client.post(
            self.url,
            self.profile_payload(
                phone="999888777",
                email="auditado@telecable.pe",
            ),
        )

        self.assertEqual(response.status_code, 302)
        event = AuditEvent.objects.get(
            actor=self.user,
            route_name="accounts:profile",
        )
        self.assertEqual(event.description, "Actualizó su perfil")
        self.assertEqual(
            event.changes["Correo"],
            {
                "before": "viejo@telecable.pe",
                "after": "auditado@telecable.pe",
            },
        )
        self.assertEqual(
            event.changes["Teléfono"],
            {
                "before": "—",
                "after": "999888777",
            },
        )


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
