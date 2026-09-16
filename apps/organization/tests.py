from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.organization.context_processors import (
    ACTIVE_BRANCH_SESSION_KEY,
    ACTIVE_OFFICE_SESSION_KEY,
)
from apps.organization.models import Branch, Office


class ActiveBranchTests(TestCase):
    """
    Sede activa: desde qué sede se consulta, no a qué sede pertenece el
    operador.

    La regla de negocio que fijan estas pruebas es que un ATC de Huancayo
    puede atender a un abonado de Oroya sin derivar la llamada, y que
    hacerlo no cambia su asignación.
    """

    def setUp(self):
        self.huancayo = Branch.objects.get(code="HUANCAYO")
        self.huancayo_office = Office.objects.create(
            branch=self.huancayo,
            code="HYO-01",
            name="Oficina Principal",
        )

        self.oroya = Branch.objects.get(code="OROYA")
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
            office=self.huancayo_office,
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
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_anonymous_user_cannot_switch_branch(self):
        self.client.logout()
        response = self.client.post(self.url, {"branch": self.oroya.pk})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.headers["Location"])

    def test_changing_branch_lands_on_the_search(self):
        response = self.client.post(self.url, {"branch": self.oroya.pk})
        self.assertRedirects(response, reverse("customers:search"))

    def test_changing_branch_is_no_springboard_to_another_site(self):
        response = self.client.post(
            self.url,
            {
                "branch": self.oroya.pk,
                "next": "https://sitio-externo.example.com/",
            },
        )
        self.assertRedirects(response, reverse("customers:search"))

    def test_changing_branch_forgets_the_customer_being_consulted(self):
        session = self.client.session
        session["selected_customer_id"] = 12345
        session.save()

        self.client.post(self.url, {"branch": self.oroya.pk})
        self.assertNotIn("selected_customer_id", self.client.session)

    def test_changing_office_lands_on_the_search_too(self):
        response = self.client.post(
            reverse("organization:set_active_office"),
            {"office": self.huancayo_office.pk},
        )
        self.assertRedirects(response, reverse("customers:search"))

    def test_changing_office_keeps_the_customer(self):
        session = self.client.session
        session["selected_customer_id"] = 12345
        session.save()

        self.client.post(
            reverse("organization:set_active_office"),
            {"office": self.huancayo_office.pk},
        )
        self.assertEqual(self.client.session["selected_customer_id"], 12345)

    def test_user_without_branch_defaults_to_huancayo(self):
        self.user.branch = None
        self.user.office = None
        self.user.save(update_fields=["branch", "office"])

        response = self.client.get(reverse("customers:search"))
        self.assertEqual(response.context["active_branch"], self.huancayo)

    def test_primary_office_is_available_for_existing_atc(self):
        response = self.client.get(reverse("customers:search"))
        self.assertIn(
            self.huancayo_office,
            response.context["available_offices"],
        )
        self.assertEqual(response.context["active_office"], self.huancayo_office)

    def test_explicitly_authorized_physical_office_is_offered(self):
        extra = Office.objects.create(
            branch=self.huancayo,
            code="HYO-02",
            name="Oficina 2",
        )
        self.user.allowed_offices.add(extra)

        response = self.client.get(reverse("customers:search"))
        self.assertIn(extra, response.context["available_offices"])

    def test_unauthorized_physical_office_is_hidden_from_atc(self):
        denied = Office.objects.create(
            branch=self.huancayo,
            code="HYO-DENIED",
            name="Caja restringida",
        )

        response = self.client.get(reverse("customers:search"))
        self.assertNotIn(denied, response.context["available_offices"])

    def test_atc_cannot_select_unauthorized_physical_office_by_post(self):
        denied = Office.objects.create(
            branch=self.huancayo,
            code="HYO-DENIED2",
            name="Caja restringida 2",
        )

        response = self.client.post(
            reverse("organization:set_active_office"),
            {"office": denied.pk},
        )

        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(
            self.client.session.get(ACTIVE_OFFICE_SESSION_KEY),
            denied.pk,
        )

    def test_atc_can_select_an_explicitly_authorized_office(self):
        extra = Office.objects.create(
            branch=self.huancayo,
            code="HYO-AUTH",
            name="Caja habilitada",
        )
        self.user.allowed_offices.add(extra)

        response = self.client.post(
            reverse("organization:set_active_office"),
            {"office": extra.pk},
        )

        self.assertRedirects(response, reverse("customers:search"))
        self.assertEqual(
            self.client.session[ACTIVE_OFFICE_SESSION_KEY],
            extra.pk,
        )

    def test_deposit_is_available_to_atc_without_manual_assignment(self):
        deposito = Office.objects.create(
            branch=self.huancayo,
            code="HYO-DEP2",
            name="Deposito",
            is_deposit=True,
        )

        response = self.client.get(reverse("customers:search"))
        self.assertIn(deposito, response.context["available_offices"])

    def test_atc_can_select_deposit_without_manual_assignment(self):
        deposito = Office.objects.create(
            branch=self.huancayo,
            code="HYO-DEP3",
            name="Deposito compartido",
            is_deposit=True,
        )

        response = self.client.post(
            reverse("organization:set_active_office"),
            {"office": deposito.pk},
        )

        self.assertRedirects(response, reverse("customers:search"))
        self.assertEqual(
            self.client.session[ACTIVE_OFFICE_SESSION_KEY],
            deposito.pk,
        )

    def test_deposit_is_never_chosen_automatically(self):
        Office.objects.filter(branch=self.huancayo).update(is_active=False)
        deposito = Office.objects.create(
            branch=self.huancayo,
            code="HYO-DEP",
            name="A Deposito",
            is_deposit=True,
        )

        self.user.office = None
        self.user.save(update_fields=["office"])

        response = self.client.get(reverse("customers:search"))
        self.assertIsNone(response.context["active_office"])
        self.assertNotEqual(response.context["active_office"], deposito)
        self.assertIn(deposito, response.context["available_offices"])

    def test_first_authorized_physical_office_is_default_without_primary(self):
        self.user.office = None
        self.user.save(update_fields=["office"])

        authorized = Office.objects.create(
            branch=self.huancayo,
            code="HYO-AUTO",
            name="A Caja habilitada",
        )
        self.user.allowed_offices.add(authorized)

        response = self.client.get(reverse("customers:search"))
        self.assertEqual(response.context["active_office"], authorized)

    def test_revoked_office_left_in_session_is_ignored(self):
        revoked = Office.objects.create(
            branch=self.huancayo,
            code="HYO-REV",
            name="Caja revocada",
        )
        self.user.allowed_offices.add(revoked)

        session = self.client.session
        session[ACTIVE_OFFICE_SESSION_KEY] = revoked.pk
        session.save()

        self.user.allowed_offices.remove(revoked)

        response = self.client.get(reverse("customers:search"))
        self.assertNotEqual(response.context["active_office"], revoked)
        self.assertNotIn(revoked, response.context["available_offices"])

    def test_admin_role_sees_every_active_office(self):
        unrestricted = Office.objects.create(
            branch=self.huancayo,
            code="HYO-ADMIN",
            name="Solo admin en esta prueba",
        )
        admin = User.objects.create_user(
            username="admin_role",
            password="ClaveSegura123",
            role=User.Role.ADMIN,
            branch=self.huancayo,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("customers:search"))
        self.assertIn(unrestricted, response.context["available_offices"])
