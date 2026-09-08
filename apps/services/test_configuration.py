"""
Configurar > Planes y Servicios.

Lo que se fija aquí es de dónde sale el precio de pronto pago: se calcula con
el descuento de la política de cobro y no se guarda aparte. Guardar las dos
cifras crearía dos fuentes que pueden dejar de coincidir, y entonces nadie
sabría cuál se le cobra al abonado.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils.formats import number_format

from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch
from apps.services.models import BillingPolicy, Plan, ServiceType

User = get_user_model()


class ConfigurationTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="SED01", name="Sede Central")

        # La migracion 0006 ya siembra las politicas de cobro en toda base,
        # incluida la de pruebas: se actualiza la fila existente en vez de
        # crear una nueva, que chocaria con el codigo unico.
        self.service_type, _ = ServiceType.objects.get_or_create(
            code="INTERNET",
            defaults={"name": "Internet"},
        )

        self.policy, _ = BillingPolicy.objects.update_or_create(
            code="ANNIVERSARY_PP10",
            defaults={
                "name": "Aniversario - pronto pago S/ 10",
                "billing_mode": BillingPolicy.Mode.ANNIVERSARY,
                "discount_amount": Decimal("10.00"),
                "discount_days_before_due": 2,
                "cut_days_after_due": 1,
            },
        )

        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="INT-2026-STD-400",
            name="PLAN INTERNET TELECABLE 400MG - 2026",
            generation=2026,
            commercial_category=Plan.Category.TELECABLE,
            billing_policy=self.policy,
            speed_mbps=400,
            monthly_price=Decimal("69.00"),
        )

    def make_user(self, username, permissions=()):
        user = User.objects.create_user(
            username=username,
            password="test1234",
            role=User.Role.ATC,
            branch=self.branch,
        )

        for codename in permissions:
            user.user_permissions.add(
                Permission.objects.get(
                    codename=codename,
                    content_type__app_label="services",
                )
            )

        return user

    def login(self, user):
        self.client.login(username=user.username, password="test1234")

        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = self.branch.pk
        session.save()


class PlanPricingTests(ConfigurationTestCase):
    def test_the_early_payment_price_is_the_normal_minus_the_discount(self):
        self.assertEqual(self.plan.monthly_price, Decimal("69.00"))
        self.assertEqual(self.plan.early_payment_price, Decimal("59.00"))

    def test_a_plan_without_a_policy_has_no_early_payment_price(self):
        """Sin política no hay pronto pago que ofrecer.

        Devolver un precio rebajado igual prometería un descuento que ninguna
        regla puede conceder.
        """
        self.plan.billing_policy = None
        self.plan.save()

        self.assertEqual(self.plan.early_payment_price, self.plan.monthly_price)
        self.assertEqual(self.plan.early_payment_discount, Decimal("0.00"))

    def test_the_2026_commercial_tiers_exist(self):
        """Los niveles con los que se vende la línea 2026."""
        available = dict(Plan.Category.choices)

        for value in ("TELECABLE", "STANDARD", "PREMIUM", "PREMIUM_PLUS"):
            self.assertIn(value, available)

    def test_the_older_tiers_are_kept(self):
        """Hay suscripciones vivas contratadas con las líneas anteriores."""
        available = dict(Plan.Category.choices)

        self.assertIn("ECONOMIC", available)
        self.assertIn("SUPER_ECONOMIC", available)


class PlanListViewTests(ConfigurationTestCase):
    def url(self):
        return reverse("services:plan_list")

    def test_without_permission_it_is_forbidden(self):
        self.login(self.make_user("sinpermiso"))

        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_it_shows_both_prices(self):
        """La lista muestra pronto pago y normal, las dos cifras de la venta.

        Se compara con el formato del propio Django y no con "59.00" literal:
        el proyecto corre en es, donde el separador decimal es la coma, y
        fijar el punto haria fallar la prueba por el idioma y no por el precio.
        """
        self.login(self.make_user("consulta1", permissions=["view_plan"]))

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PLAN INTERNET TELECABLE 400MG - 2026")
        self.assertContains(response, number_format(Decimal("59.00"), 2))
        self.assertContains(response, number_format(Decimal("69.00"), 2))

    def test_consulting_does_not_grant_editing(self):
        self.login(self.make_user("consulta2", permissions=["view_plan"]))

        response = self.client.get(self.url())

        self.assertFalse(response.context["can_edit"])
        self.assertFalse(response.context["can_create"])
        self.assertNotContains(response, reverse("services:plan_create"))

    def test_it_filters_by_service(self):
        cable = ServiceType.objects.create(code="CABLE", name="Cable")
        Plan.objects.create(
            service_type=cable,
            code="CABLE-TEST",
            name="Plan cable de prueba",
            monthly_price=Decimal("40.00"),
        )

        self.login(self.make_user("consulta3", permissions=["view_plan"]))

        response = self.client.get(self.url(), {"servicio": "CABLE"})

        self.assertContains(response, "Plan cable de prueba")
        self.assertNotContains(response, "PLAN INTERNET TELECABLE 400MG - 2026")

    def test_it_can_hide_inactive_plans(self):
        Plan.objects.create(
            service_type=self.service_type,
            code="INT-RETIRADO",
            name="Plan retirado",
            monthly_price=Decimal("30.00"),
            is_active=False,
        )

        self.login(self.make_user("consulta4", permissions=["view_plan"]))

        response = self.client.get(self.url(), {"activos": "1"})

        self.assertNotContains(response, "Plan retirado")


class PlanFormViewTests(ConfigurationTestCase):
    def test_creating_a_plan_requires_the_permission(self):
        self.login(self.make_user("consulta1", permissions=["view_plan"]))

        self.assertEqual(
            self.client.get(reverse("services:plan_create")).status_code, 403
        )

    def test_a_plan_is_created_with_its_normal_price(self):
        self.login(
            self.make_user("comercial1", permissions=["view_plan", "add_plan"])
        )

        response = self.client.post(
            reverse("services:plan_create"),
            {
                "service_type": self.service_type.pk,
                "code": "INT-2026-STD-600",
                "name": "PLAN INTERNET ESTANDAR 600MG - 2026",
                "generation": 2026,
                "commercial_category": Plan.Category.STANDARD,
                "billing_policy": self.policy.pk,
                "speed_mbps": 600,
                "technology": "FTTH",
                "monthly_price": "79.00",
                "included_tv_points": 0,
                "is_active": "on",
            },
        )

        plan = Plan.objects.get(code="INT-2026-STD-600")

        self.assertRedirects(response, reverse("services:plan_list"))
        self.assertEqual(plan.monthly_price, Decimal("79.00"))
        self.assertEqual(plan.early_payment_price, Decimal("69.00"))

    def test_a_discount_that_reaches_the_price_is_rejected(self):
        """El plan no puede quedar gratis por pagar puntual."""
        self.login(
            self.make_user("comercial2", permissions=["view_plan", "add_plan"])
        )

        response = self.client.post(
            reverse("services:plan_create"),
            {
                "service_type": self.service_type.pk,
                "code": "INT-BARATO",
                "name": "Plan mas barato que su descuento",
                "generation": 2026,
                "commercial_category": Plan.Category.TELECABLE,
                "billing_policy": self.policy.pk,
                "speed_mbps": 100,
                "monthly_price": "8.00",
                "included_tv_points": 0,
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Plan.objects.filter(code="INT-BARATO").exists())

    def test_the_code_is_not_editable_once_the_plan_exists(self):
        """Hay suscripciones apuntando al plan: el código es su identidad."""
        self.login(
            self.make_user("comercial3", permissions=["view_plan", "change_plan"])
        )

        response = self.client.get(
            reverse("services:plan_edit", kwargs={"pk": self.plan.pk})
        )

        self.assertTrue(response.context["form"].fields["code"].disabled)

    def test_editing_updates_the_price(self):
        self.login(
            self.make_user("comercial4", permissions=["view_plan", "change_plan"])
        )

        self.client.post(
            reverse("services:plan_edit", kwargs={"pk": self.plan.pk}),
            {
                "service_type": self.service_type.pk,
                "name": "PLAN INTERNET TELECABLE 400MG - 2026",
                "generation": 2026,
                "commercial_category": Plan.Category.TELECABLE,
                "billing_policy": self.policy.pk,
                "speed_mbps": 400,
                "technology": "FTTH",
                "monthly_price": "75.00",
                "included_tv_points": 0,
                "is_active": "on",
            },
        )

        self.plan.refresh_from_db()

        self.assertEqual(self.plan.monthly_price, Decimal("75.00"))
        self.assertEqual(self.plan.early_payment_price, Decimal("65.00"))


class ServiceTypeViewTests(ConfigurationTestCase):
    def test_without_permission_the_list_is_forbidden(self):
        self.login(self.make_user("sinpermiso"))

        self.assertEqual(
            self.client.get(reverse("services:servicetype_list")).status_code, 403
        )

    def test_the_list_counts_the_active_plans(self):
        self.login(
            self.make_user("consulta1", permissions=["view_servicetype"])
        )

        response = self.client.get(reverse("services:servicetype_list"))
        row = response.context["service_types"].get(code="INTERNET")

        self.assertEqual(row.plan_count, 1)

    def test_a_service_is_created_with_its_code_upper_cased(self):
        self.login(
            self.make_user(
                "comercial1", permissions=["view_servicetype", "add_servicetype"]
            )
        )

        response = self.client.post(
            reverse("services:servicetype_create"),
            {
                "code": "duo",
                "name": "Duo",
                "description": "Internet y cable.",
                "supports_tv_annexes": "on",
                "annex_installation_price": "5.00",
                "annex_monthly_price": "5.00",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("services:servicetype_list"))
        self.assertTrue(ServiceType.objects.filter(code="DUO").exists())

    def test_the_code_is_not_editable_once_the_service_exists(self):
        """El catálogo de órdenes referencia el servicio por su código."""
        self.login(
            self.make_user(
                "comercial2",
                permissions=["view_servicetype", "change_servicetype"],
            )
        )

        response = self.client.get(
            reverse(
                "services:servicetype_edit", kwargs={"pk": self.service_type.pk}
            )
        )

        self.assertTrue(response.context["form"].fields["code"].disabled)


class ConfigureMenuTests(ConfigurationTestCase):
    """La sección Configurar del menú lateral."""

    def test_it_shows_both_entries_to_who_may_see_them(self):
        self.login(
            self.make_user(
                "consulta1", permissions=["view_plan", "view_servicetype"]
            )
        )

        response = self.client.get(reverse("services:plan_list"))

        self.assertContains(response, reverse("services:plan_list"))
        self.assertContains(response, reverse("services:servicetype_list"))

    def test_it_hides_what_the_user_may_not_see(self):
        self.login(self.make_user("consulta2", permissions=["view_plan"]))

        response = self.client.get(reverse("services:plan_list"))

        self.assertNotContains(response, reverse("services:servicetype_list"))
