"""
Escenario base de las pruebas de cobranza.

Monta un abonado con una suscripción activa y una política de cobro por mes
calendario con pronto pago, que es el caso que cubre a la mayoría de abonados.
Las pruebas que necesiten aniversario cambian la política sobre esta base.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from apps.customers.models import Customer, CustomerAddress
from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch, Zone
from apps.services.models import BillingPolicy, Plan, ServiceType, Subscription

User = get_user_model()


class PaymentsTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="SED01", name="Sede Central")
        self.zone = Zone.objects.create(branch=self.branch, name="Zona Norte")

        self.customer = Customer.objects.create(
            code="CLI001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="45678912",
            first_name="Juan",
            paternal_surname="Pérez",
            maternal_surname="Ramos",
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Av. Los Álamos 123",
            district="Chachapoyas",
            is_primary=True,
        )

        self.service_type = ServiceType.objects.create(
            code="INTERNET",
            name="Internet",
        )

        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN100",
            name="Fibra 100 Mbps",
            speed_mbps=100,
            monthly_price=80,
        )

        # Mes calendario: vence al cerrar el mes, pronto pago hasta el 10 y
        # corte el 15 del mes siguiente.
        self.policy = BillingPolicy.objects.create(
            code="MENSUAL",
            name="Mes calendario",
            billing_mode=BillingPolicy.Mode.CALENDAR_MONTH,
            discount_amount=5,
            discount_deadline_day=10,
            cut_day_next_month=15,
        )

        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            billing_policy=self.policy,
            status=Subscription.Status.ACTIVE,
            base_monthly_fee=80,
            installation_date=date(2026, 1, 15),
        )

        self.cashier = self.make_user("caja1")

    def make_user(self, username, permissions=(), role=None):
        user = User.objects.create_user(
            username=username,
            password="test1234",
            role=role or User.Role.ATC,
            branch=self.branch,
        )

        for codename in permissions:
            user.user_permissions.add(
                Permission.objects.get(
                    codename=codename,
                    content_type__app_label="payments",
                )
            )

        return user

    def login(self, user):
        self.client.login(username=user.username, password="test1234")

        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = self.branch.pk
        session.save()

    def select_customer(self, customer=None):
        """Deja un abonado elegido en la sesión, como hace 'Usar cliente'."""
        session = self.client.session
        session["selected_customer_id"] = (customer or self.customer).pk
        session.save()
