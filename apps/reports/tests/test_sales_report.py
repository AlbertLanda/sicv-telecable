from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer, CustomerAddress
from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription


User = get_user_model()


class SalesReportTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            code="HYO-REPORT",
            name="Huancayo",
        )
        self.zone = Zone.objects.create(
            branch=self.branch,
            name="Centro",
        )

        self.admin = User.objects.create_user(
            username="admin_sales_report",
            password="123",
            role=User.Role.ADMIN,
            branch=self.branch,
        )
        self.registrar = User.objects.create_user(
            username="atc_registra",
            password="123",
            role=User.Role.ATC,
            branch=self.branch,
        )
        self.seller = User.objects.create_user(
            username="atc_vende",
            password="123",
            role=User.Role.ATC,
            branch=self.branch,
            is_salesperson=True,
        )

        self.service = ServiceType.objects.create(
            code="INTERNET-REPORT",
            name="Internet reporte",
        )
        self.plan = Plan.objects.create(
            service_type=self.service,
            code="PLAN-REPORT",
            name="Plan reporte",
            monthly_price=69,
        )

        self.customer = Customer.objects.create(
            code="HY01-A9000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="70000001",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Reporte",
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Av. Reporte 100",
            district="Huancayo",
            is_primary=True,
        )
        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service,
            plan=self.plan,
            seller=self.seller,
            registered_by=self.registrar,
            status=Subscription.Status.PRESALE,
        )

        self.url = reverse("reports:sales")
        self.client.login(
            username="admin_sales_report",
            password="123",
        )
        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = self.branch.pk
        session.save()

    def test_report_counts_sales_by_the_real_seller(self):
        response = self.client.get(
            self.url,
            {"day": timezone.localdate().isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report"]["total_sales"], 1)
        self.assertEqual(response.context["report"]["seller_count"], 1)
        self.assertContains(response, str(self.seller))
        self.assertContains(response, str(self.registrar))
        self.assertContains(response, self.subscription.service_code)

    def test_report_can_filter_one_seller(self):
        other_seller = User.objects.create_user(
            username="otro_vendedor",
            password="123",
            role=User.Role.SALES,
            branch=self.branch,
        )
        other_customer = Customer.objects.create(
            code="HY01-A9000002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="70000002",
            person_type=Customer.PersonType.NATURAL,
            first_name="Otro",
            paternal_surname="Cliente",
        )
        other_address = CustomerAddress.objects.create(
            customer=other_customer,
            zone=self.zone,
            address="Av. Reporte 200",
            district="Huancayo",
            is_primary=True,
        )
        Subscription.objects.create(
            customer=other_customer,
            address=other_address,
            service_type=self.service,
            plan=self.plan,
            seller=other_seller,
            registered_by=self.registrar,
            status=Subscription.Status.PRESALE,
        )

        response = self.client.get(
            self.url,
            {
                "day": timezone.localdate().isoformat(),
                "seller": self.seller.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report"]["total_sales"], 1)

        rows = list(response.context["report"]["rows"])
        self.assertEqual(rows, [self.subscription])
        self.assertEqual(rows[0].seller, self.seller)
        self.assertNotEqual(rows[0].seller, other_seller)

    def test_report_does_not_mix_another_active_branch(self):
        other_branch = Branch.objects.create(
            code="JAU-REPORT",
            name="Jauja",
        )
        other_zone = Zone.objects.create(
            branch=other_branch,
            name="Jauja centro",
        )
        other_customer = Customer.objects.create(
            code="JA01-A9000001",
            branch=other_branch,
            document_type=Customer.DocumentType.DNI,
            document_number="70000003",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Jauja",
        )
        other_address = CustomerAddress.objects.create(
            customer=other_customer,
            zone=other_zone,
            address="Jr. Jauja 100",
            district="Jauja",
            is_primary=True,
        )
        Subscription.objects.create(
            customer=other_customer,
            address=other_address,
            service_type=self.service,
            plan=self.plan,
            seller=self.seller,
            registered_by=self.registrar,
            status=Subscription.Status.PRESALE,
        )

        response = self.client.get(
            self.url,
            {"day": timezone.localdate().isoformat()},
        )

        self.assertEqual(response.context["report"]["total_sales"], 1)
        self.assertContains(response, self.subscription.service_code)
        self.assertNotContains(response, "Jr. Jauja 100")
