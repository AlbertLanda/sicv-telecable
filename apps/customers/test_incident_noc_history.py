from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.models import IncidentDetail, OrderType, WorkOrder

from .models import Customer, CustomerAddress


User = get_user_model()


class CustomerIncidentNocHistoryTests(TestCase):
    """La pestaña de órdenes trata una incidencia como historial NOC, no campo."""

    def setUp(self):
        self.branch = Branch.objects.create(code="JAUJA", name="Jauja")
        self.zone = Zone.objects.create(branch=self.branch, name="Centro")
        self.user = User.objects.create_user(
            username="noc_dashboard",
            password="test1234",
            role=User.Role.NOC,
            branch=self.branch,
        )
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_workorder"),
            Permission.objects.get(codename="view_incident"),
        )

        self.customer = Customer.objects.create(
            code="JA01-A0000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="70000001",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Prueba",
            phone="963200241",
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Prueba 123",
            district="Jauja",
            is_primary=True,
        )
        self.service_type = ServiceType.objects.create(
            code="INTERNET_NOC_TEST",
            name="Internet",
        )
        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN_NOC_TEST",
            name="Internet 600 Mbps",
            speed_mbps=600,
        )
        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=1,
        )
        self.incident_type = OrderType.objects.create(
            code="INCIDENT",
            name="Incidencia",
        )
        self.incident = WorkOrder.objects.create(
            order_number="OT-2026-900001",
            subscription=self.subscription,
            order_type=self.incident_type,
            branch=self.branch,
            zone=self.zone,
            attention_type=WorkOrder.AttentionType.SYSTEM,
            status=WorkOrder.Status.ATTENDED,
            reason_text="Internet lento",
            created_by=self.user,
            started_at=timezone.now(),
            attended_at=timezone.now(),
        )
        IncidentDetail.objects.create(
            work_order=self.incident,
            attention_detail="Se corrigió la configuración WAN y el cliente confirmó navegación estable.",
            observations="Sin nuevas pérdidas durante la validación.",
            attended_by=self.user,
        )

        self.client.login(username="noc_dashboard", password="test1234")

    def test_orders_tab_links_incident_to_noc_history_and_shows_solution(self):
        response = self.client.get(
            reverse("customers:orders", kwargs={"pk": self.customer.pk})
        )

        history_url = reverse(
            "work_orders:incident_noc_detail",
            kwargs={"pk": self.incident.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, history_url)
        self.assertContains(response, "Ver historial NOC")
        self.assertContains(response, "Resultado / solución")
        self.assertContains(response, "Se corrigió la configuración WAN")
        self.assertContains(response, "NOC · noc_dashboard")
        self.assertNotContains(response, "Ver ficha técnica")

    def test_open_incident_featured_card_uses_noc_flow_not_field_flow(self):
        self.incident.status = WorkOrder.Status.PENDING
        self.incident.attended_at = None
        self.incident.save(update_fields=["status", "attended_at", "updated_at"])

        response = self.client.get(
            reverse("customers:orders", kwargs={"pk": self.customer.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Abrir historial NOC")
        self.assertContains(
            response,
            reverse(
                "work_orders:incident_noc_detail",
                kwargs={"pk": self.incident.pk},
            ),
        )
        self.assertNotContains(response, "Ver liquidación técnica")
