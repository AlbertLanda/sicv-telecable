"""
El dashboard: la portada del SICV.

Lo que se fija aquí es que cada cifra cuente lo mismo que la pantalla a la que
lleva -la agenda, la cola NOC, el reporte de ventas- o, donde esa pantalla no
existe todavía, lo que dice la regla del modelo; que se cuente en la sede
activa; y que cada bloque solo se le muestre a quien puede abrir su módulo.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.payments.models import Charge, Payment, PaymentCommitment
from apps.payments.services import register_payment
from apps.payments.tests.base import PaymentsTestCase
from apps.services.models import Subscription
from apps.work_orders.models import OrderType, WorkOrder


class DashboardTestCase(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()
        self.other_branch = Branch.objects.create(code="SED02", name="Jauja")
        self.other_zone = Zone.objects.create(branch=self.other_branch, name="Centro")
        self.sequence = 0

    def url(self):
        return reverse("dashboard")

    def grant(self, user, *perms):
        for perm in perms:
            app_label, codename = perm.split(".")
            user.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label=app_label, codename=codename
                )
            )

    def viewer(self, *perms):
        self.sequence += 1
        user = self.make_user(f"tablero{self.sequence}")
        self.grant(user, *perms)
        self.login(user)

        return user

    def figure(self, response, label):
        for section in response.context["sections"]:
            for figure in section.figures:
                if figure.label == label:
                    return figure

        return None

    def open_dashboard(self):
        return self.client.get(self.url())

    def customer_elsewhere(self):
        """Un abonado de otra sede, con su servicio."""
        customer = Customer.objects.create(
            code="CLI900",
            branch=self.other_branch,
            document_type=Customer.DocumentType.DNI,
            document_number="40000009",
            first_name="Ana",
            paternal_surname="Rojas",
            maternal_surname="Vela",
        )
        address = CustomerAddress.objects.create(
            customer=customer,
            zone=self.other_zone,
            address="Jr. Junín 45",
            is_primary=True,
        )
        subscription = Subscription.objects.create(
            customer=customer,
            address=address,
            service_type=self.service_type,
            plan=self.plan,
            billing_policy=self.policy,
            status=Subscription.Status.ACTIVE,
            base_monthly_fee=80,
        )

        return customer, subscription


class LaPortadaTests(DashboardTestCase):
    def test_login_lands_on_the_dashboard(self):
        self.make_user("entra1")

        response = self.client.post(
            reverse("login"), {"username": "entra1", "password": "test1234"}
        )

        self.assertRedirects(response, self.url(), fetch_redirect_response=False)

    def test_anonymous_goes_to_login(self):
        response = self.open_dashboard()

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_the_sidebar_offers_it_first_and_no_longer_pending(self):
        self.viewer()
        body = self.open_dashboard().content.decode()

        self.assertLess(
            body.index(f'href="{self.url()}"'), body.index("Buscar cliente")
        )
        self.assertNotIn(
            '<span>Dashboard</span><span class="pending-tag">', body
        )
        self.assertIn('aria-current="page"', body)

    def test_without_permissions_it_says_so_instead_of_forbidding(self):
        """Es la primera pantalla tras el login: un 403 ahí no se entiende."""
        self.viewer()
        response = self.open_dashboard()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sections"], [])
        self.assertContains(response, "todavía no tiene cifras asignadas")

    def test_each_block_needs_its_module(self):
        self.viewer("payments.view_payment")
        claves = [section.key for section in self.open_dashboard().context["sections"]]

        self.assertEqual(claves, ["cobranza"])


class CobranzaTests(DashboardTestCase):
    def pay(self, amount, branch=None, **kwargs):
        charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo",
            amount=Decimal(amount),
            due_date=self.today + timedelta(days=5),
        )

        return register_payment(
            customer=self.customer,
            amount=Decimal(amount),
            method=Payment.Method.CASH,
            branch=branch or self.branch,
            user=self.cashier,
            allocations=[(charge, Decimal(amount))],
            **kwargs,
        )

    def test_collected_today_counts_only_confirmed_money_of_the_branch(self):
        self.pay("80.00")
        voided, _ = self.pay("20.00")
        voided.void(user=self.cashier, reason="Error de caja.")
        self.pay("15.00", settled=False)
        self.pay("50.00", branch=self.other_branch)

        self.viewer("payments.view_payment")
        cobrado = self.figure(self.open_dashboard(), "Cobrado hoy")

        self.assertEqual(cobrado.value, Decimal("80.00"))
        self.assertEqual(cobrado.detail, "1 cobro")

    def test_overdue_debt_is_what_is_left_to_pay(self):
        """Emitido menos lo pagado, solo de lo vencido."""
        overdue = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Vencido",
            amount=Decimal("100.00"),
            due_date=self.today - timedelta(days=3),
        )
        register_payment(
            customer=self.customer,
            amount=Decimal("30.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(overdue, Decimal("30.00"))],
        )
        Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Por vencer",
            amount=Decimal("40.00"),
            due_date=self.today + timedelta(days=3),
        )
        other_customer, _ = self.customer_elsewhere()
        Charge.objects.create(
            customer=other_customer,
            concept=Charge.Concept.OTHER,
            description="De otra sede",
            amount=Decimal("55.00"),
            due_date=self.today - timedelta(days=3),
        )

        self.viewer("payments.view_charge")
        deuda = self.figure(self.open_dashboard(), "Deuda vencida")

        self.assertEqual(deuda.value, Decimal("70.00"))
        self.assertEqual(deuda.detail, "de 1 abonado")

    def test_an_expired_commitment_no_longer_counts(self):
        """Puede seguir marcado como activo hasta que se abre la cuenta."""
        PaymentCommitment.objects.create(
            customer=self.customer,
            amount=Decimal("80.00"),
            committed_date=self.today + timedelta(days=7),
            granted_by=self.cashier,
        )
        PaymentCommitment.objects.create(
            customer=self.customer,
            amount=Decimal("80.00"),
            committed_date=self.today - timedelta(days=1),
            granted_by=self.cashier,
        )

        self.viewer("payments.view_charge")

        self.assertEqual(
            self.figure(self.open_dashboard(), "Compromisos de pago").value, 1
        )


class OperacionesTests(DashboardTestCase):
    def order(self, code, status=WorkOrder.Status.PENDING, branch=None, **fields):
        order_type, _ = OrderType.objects.get_or_create(
            code=code, defaults={"name": code}
        )
        self.sequence += 1

        return WorkOrder.objects.create(
            order_number=f"OT-{self.sequence:05d}",
            subscription=self.subscription,
            order_type=order_type,
            branch=branch or self.branch,
            attention_type=WorkOrder.AttentionType.FIELD,
            status=status,
            created_by=self.cashier,
            detail="Prueba.",
            **fields,
        )

    def test_open_orders_count_like_the_agenda_without_incidents(self):
        self.order("INSTALLATION", scheduled_date=self.today)
        self.order("INTERNET_FAULT")
        self.order("CUT", status=WorkOrder.Status.LIQUIDATED)
        self.order("TRANSFER", branch=self.other_branch)
        self.order("INCIDENT")

        self.viewer("work_orders.view_workorder")
        response = self.open_dashboard()
        abiertas = self.figure(response, "Órdenes abiertas")

        self.assertEqual(abiertas.value, 2)
        self.assertEqual(abiertas.breakdown, [("Instalación", 1), ("Avería", 1)])
        self.assertEqual(abiertas.url, reverse("work_orders:schedule_board"))
        self.assertEqual(self.figure(response, "Programadas para hoy").value, 1)
        self.assertEqual(self.figure(response, "Sin programar").value, 1)

    def test_incidents_count_like_the_noc_queue_across_branches(self):
        self.order("INCIDENT")
        self.order("INCIDENT", status=WorkOrder.Status.IN_PROGRESS, branch=self.other_branch)
        self.order("INCIDENT", status=WorkOrder.Status.ATTENDED)

        self.viewer("work_orders.view_incident")
        incidencias = self.figure(self.open_dashboard(), "Incidencias NOC abiertas")

        self.assertEqual(incidencias.value, 2)
        self.assertEqual(incidencias.detail, "1 sin tomar · todas las sedes")
        self.assertEqual(incidencias.url, reverse("work_orders:incident_noc_queue"))


class ComercialTests(DashboardTestCase):
    def test_services_are_counted_in_the_active_branch(self):
        Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            billing_policy=self.policy,
            status=Subscription.Status.PRESALE,
            base_monthly_fee=80,
            service_number=2,
        )
        Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            billing_policy=self.policy,
            status=Subscription.Status.CUT,
            base_monthly_fee=80,
            service_number=3,
        )
        self.customer_elsewhere()

        self.viewer("services.view_subscription")
        response = self.open_dashboard()

        self.assertEqual(self.figure(response, "Servicios activos").value, 1)
        self.assertEqual(self.figure(response, "Altas del mes").value, 3)
        self.assertEqual(self.figure(response, "Por instalar").value, 1)
        self.assertEqual(self.figure(response, "Cortados o suspendidos").value, 1)
