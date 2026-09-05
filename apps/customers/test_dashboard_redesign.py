from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from apps.contracts.models import Contract
from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.models import OrderReason, OrderType, WorkOrder

from .models import Customer, CustomerAddress


User = get_user_model()


class CustomerDashboardRedesignTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="HYO", name="Huancayo")
        self.zone = Zone.objects.create(branch=self.branch, name="Centro")
        self.user = User.objects.create_user(
            username="atc_dashboard",
            password="test1234",
            role=User.Role.ATC,
            branch=self.branch,
        )
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_workorder"),
            Permission.objects.get(codename="add_workorder"),
        )

        self.customer = Customer.objects.create(
            code="HY01-A0000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="72882737",
            person_type=Customer.PersonType.NATURAL,
            first_name="Albert",
            paternal_surname="Landa",
            maternal_surname="Rosario",
            phone="922181550",
            email="albert@example.com",
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Abraham Valdelomar 235",
            district="Sausa",
            reference="Al costado del vecino",
            electrical_supply_number="75018907",
            latitude="-11.7861026",
            longitude="-75.4900202",
            is_primary=True,
        )
        self.service_type = ServiceType.objects.create(code="DUO", name="Duo")
        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="DUO600",
            name="Duo 600 Mbps - Estandar 2026",
            speed_mbps=600,
        )
        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=1,
            installation_date=date(2026, 9, 5),
        )
        self.contract = Contract.objects.create(
            contract_number="CONT-000001",
            customer=self.customer,
            subscription=self.subscription,
            start_date=date(2026, 9, 4),
            status=Contract.Status.ACTIVE,
        )
        self.order_type = OrderType.objects.create(
            code="INSTALLATION_UI",
            name="Instalación",
        )
        self.reason = OrderReason.objects.create(
            order_type=self.order_type,
            code="NEW_CLIENT_UI",
            name="Cliente nuevo",
        )
        self.order = WorkOrder.objects.create(
            order_number="OT-2026-999999",
            subscription=self.subscription,
            order_type=self.order_type,
            reason=self.reason,
            branch=self.branch,
            zone=self.zone,
            status=WorkOrder.Status.PENDING,
            detail="Instalar servicio contratado.",
            created_by=self.user,
        )

        self.client.login(username="atc_dashboard", password="test1234")

    def test_dashboard_prioritizes_open_work_order_and_professional_summary(self):
        response = self.client.get(
            reverse("customers:detail", kwargs={"pk": self.customer.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "customers/detail_dashboard.html")
        self.assertContains(response, "Orden de trabajo abierta")
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, "Ver orden inicial")
        self.assertContains(response, "Imprimir orden inicial")
        self.assertContains(response, "Ver ficha técnica")
        self.assertContains(response, "CONT-000001")
        self.assertContains(response, "Duo 600 Mbps - Estandar 2026")

    def test_dashboard_never_offers_manual_assignment(self):
        assign_permission = Permission.objects.get(codename="assign_workorder")
        self.user.user_permissions.add(assign_permission)

        response = self.client.get(
            reverse("customers:detail", kwargs={"pk": self.customer.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            reverse("work_orders:assign", kwargs={"pk": self.order.pk}),
        )
        self.assertNotContains(response, "Asignar técnico")
        self.assertNotContains(response, "Reasignar técnico")

    def test_initial_order_is_separate_from_technical_view(self):
        response = self.client.get(
            reverse("work_orders:initial_print", kwargs={"pk": self.order.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "work_orders/work_order_initial_print.html")
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, "Datos de la orden emitida")
        self.assertContains(response, "Instalar servicio contratado.")
        self.assertContains(response, "Ver ficha técnica")
        self.assertNotContains(response, "Ficha técnica de campo")
        self.assertNotContains(response, "Evidencias")

    def test_print_query_enables_browser_print_mode(self):
        response = self.client.get(
            reverse("work_orders:initial_print", kwargs={"pk": self.order.pk}),
            {"print": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["auto_print"])
        self.assertContains(response, "window.print()")
