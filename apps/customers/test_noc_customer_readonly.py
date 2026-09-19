from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription

from .models import Customer, CustomerAddress


User = get_user_model()


class NocCustomerReadOnlyTests(TestCase):
    """NOC consulta al abonado para soporte, pero ATC mantiene sus datos."""

    def setUp(self):
        self.branch = Branch.objects.get(code="JAUJA")
        self.zone = Zone.objects.create(branch=self.branch, name="NOC Solo Lectura")

        self.noc = User.objects.create_user(
            username="noc_readonly",
            password="test1234",
            role=User.Role.NOC,
            branch=self.branch,
        )
        self.atc = User.objects.create_user(
            username="atc_customer_admin",
            password="test1234",
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.customer = Customer.objects.create(
            code="JA01-A0099001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="70990001",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="SoloLectura",
            phone="963200241",
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Prueba NOC 123",
            district="Jauja",
            is_primary=True,
        )
        service_type = ServiceType.objects.create(
            code="INTERNET_NOC_READONLY",
            name="Internet NOC readonly",
        )
        plan = Plan.objects.create(
            service_type=service_type,
            code="PLAN_NOC_READONLY",
            name="Plan NOC readonly",
            speed_mbps=100,
        )
        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=service_type,
            plan=plan,
            status=Subscription.Status.ACTIVE,
            service_number=1,
        )

    def test_noc_sees_customer_data_without_commercial_actions(self):
        self.client.login(username="noc_readonly", password="test1234")

        response = self.client.get(
            reverse("customers:detail", kwargs={"pk": self.customer.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.customer.phone)
        self.assertContains(response, self.address.address)
        self.assertNotContains(response, "Editar datos")
        self.assertNotContains(response, "Nueva dirección")
        self.assertNotContains(response, "Nueva suscripción")
        self.assertNotContains(response, "Nuevo contrato")
        self.assertNotContains(response, "Más opciones")

    def test_noc_cannot_bypass_readonly_mode_with_direct_urls(self):
        self.client.login(username="noc_readonly", password="test1234")

        protected_urls = [
            reverse("customers:create"),
            reverse(
                "customers:general_edit",
                kwargs={"customer_pk": self.customer.pk},
            ),
            reverse(
                "customers:address_create",
                kwargs={"customer_pk": self.customer.pk},
            ),
            reverse(
                "services:subscription_create",
                kwargs={"customer_pk": self.customer.pk},
            ),
            reverse(
                "contracts:contract_create",
                kwargs={"customer_pk": self.customer.pk},
            ),
        ]

        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)

    def test_atc_keeps_customer_commercial_permissions_and_actions(self):
        expected_permissions = [
            "customers.add_customer",
            "customers.change_customer",
            "customers.add_customeraddress",
            "services.add_subscription",
            "contracts.add_contract",
        ]
        for permission in expected_permissions:
            with self.subTest(permission=permission):
                self.assertTrue(self.atc.has_perm(permission))

        self.client.login(username="atc_customer_admin", password="test1234")
        response = self.client.get(
            reverse("customers:detail", kwargs={"pk": self.customer.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Editar datos")
        self.assertContains(response, "Nueva dirección")
        self.assertContains(response, "Nueva suscripción")
        self.assertContains(response, "Nuevo contrato")
