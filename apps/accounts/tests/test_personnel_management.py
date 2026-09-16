from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.organization.models import Branch, Office


class PersonnelManagementTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            code="PER-TEST",
            name="Sede Personal Test",
        )
        self.other_branch = Branch.objects.create(
            code="PER-OTRA",
            name="Otra Sede Personal",
        )
        self.main_office = Office.objects.create(
            branch=self.branch,
            code="PER-01",
            name="Local Principal",
        )
        self.cash_office = Office.objects.create(
            branch=self.branch,
            code="PER-02",
            name="Caja 2",
        )
        self.deposit = Office.objects.create(
            branch=self.branch,
            code="PER-DEP",
            name="Deposito",
            is_deposit=True,
        )
        self.foreign_office = Office.objects.create(
            branch=self.other_branch,
            code="PER-OTRA-01",
            name="Caja ajena",
        )
        self.accounting = User.objects.create_user(
            username="sandra_test",
            password="Telecable-2026-Sandra!",
            role=User.Role.ACCOUNTING,
            branch=self.branch,
            is_active=True,
        )
        self.atc = User.objects.create_user(
            username="atc_personnel_test",
            password="Telecable-2026-ATC!",
            role=User.Role.ATC,
            branch=self.branch,
            is_active=True,
        )

    def test_accounting_can_open_personnel_list(self):
        self.client.force_login(self.accounting)

        response = self.client.get(reverse("accounts:personnel_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Personal")
        self.assertContains(response, self.atc.username)
        self.assertContains(response, "Nuevo personal")

    def test_atc_cannot_open_personnel_list(self):
        self.client.force_login(self.atc)

        response = self.client.get(reverse("accounts:personnel_list"))

        self.assertEqual(response.status_code, 403)

    def test_accounting_can_create_atc_with_authorized_cash_offices(self):
        self.client.force_login(self.accounting)

        response = self.client.post(
            reverse("accounts:personnel_create"),
            {
                "username": "atc_nueva",
                "first_name": "Nueva",
                "last_name": "Operadora",
                "email": "nueva@example.com",
                "phone": "999999999",
                "role": User.Role.ATC,
                "branch": self.branch.pk,
                "office": self.main_office.pk,
                "allowed_offices": [self.main_office.pk, self.cash_office.pk],
                "is_active": "on",
                "password1": "Telecable-2026-Nueva!",
                "password2": "Telecable-2026-Nueva!",
            },
        )

        self.assertRedirects(response, reverse("accounts:personnel_list"))
        created = User.objects.get(username="atc_nueva")
        self.assertTrue(created.check_password("Telecable-2026-Nueva!"))
        self.assertEqual(created.role, User.Role.ATC)
        self.assertEqual(created.office, self.main_office)
        self.assertSetEqual(
            set(created.allowed_offices.all()),
            {self.main_office, self.cash_office},
        )

    def test_deposit_is_not_offered_as_assignable_cash_office(self):
        self.client.force_login(self.accounting)

        response = self.client.get(reverse("accounts:personnel_create"))

        self.assertNotContains(response, f'value="{self.deposit.pk}"')
        self.assertContains(response, "disponibles automáticamente")

    def test_cross_branch_cash_office_is_rejected(self):
        self.client.force_login(self.accounting)

        response = self.client.post(
            reverse("accounts:personnel_edit", kwargs={"pk": self.atc.pk}),
            {
                "username": self.atc.username,
                "first_name": self.atc.first_name,
                "last_name": self.atc.last_name,
                "email": self.atc.email,
                "phone": self.atc.phone,
                "role": User.Role.ATC,
                "branch": self.branch.pk,
                "office": self.foreign_office.pk,
                "allowed_offices": [self.foreign_office.pk],
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "debe pertenecer a la sede seleccionada")
        self.atc.refresh_from_db()
        self.assertNotEqual(self.atc.office, self.foreign_office)

    def test_accounting_cannot_assign_admin_role(self):
        self.client.force_login(self.accounting)

        response = self.client.post(
            reverse("accounts:personnel_create"),
            {
                "username": "admin_inventado",
                "role": User.Role.ADMIN,
                "branch": self.branch.pk,
                "is_active": "on",
                "password1": "Telecable-2026-Admin!",
                "password2": "Telecable-2026-Admin!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="admin_inventado").exists())

    def test_accounting_cannot_edit_superuser(self):
        root = User.objects.create_superuser(
            username="root_personnel_test",
            password="Telecable-2026-Root!",
            role=User.Role.ADMIN,
        )
        self.client.force_login(self.accounting)

        response = self.client.get(
            reverse("accounts:personnel_edit", kwargs={"pk": root.pk})
        )

        self.assertEqual(response.status_code, 403)

    def test_non_atc_does_not_keep_cash_office_authorizations(self):
        self.atc.allowed_offices.add(self.cash_office)
        self.client.force_login(self.accounting)

        response = self.client.post(
            reverse("accounts:personnel_edit", kwargs={"pk": self.atc.pk}),
            {
                "username": self.atc.username,
                "first_name": self.atc.first_name,
                "last_name": self.atc.last_name,
                "email": self.atc.email,
                "phone": self.atc.phone,
                "role": User.Role.NOC,
                "branch": self.branch.pk,
                "office": self.main_office.pk,
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("accounts:personnel_list"))
        self.atc.refresh_from_db()
        self.assertEqual(self.atc.role, User.Role.NOC)
        self.assertFalse(self.atc.allowed_offices.exists())
