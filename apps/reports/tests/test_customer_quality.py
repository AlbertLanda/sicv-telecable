"""Casos sintéticos: las alertas no autorizan cambios ni certifican datos."""

from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerAddress
from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch
from apps.reports.customer_quality import customers_with_quality_flags, issues_for, quality_summary


class CustomerQualityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(code="QUALITY-A", name="Sede de prueba A")
        cls.other_branch = Branch.objects.create(code="QUALITY-B", name="Sede de prueba B")
        cls.user = User.objects.create_user(username="quality-atc", role=User.Role.ATC, branch=cls.branch)
        cls.url = reverse("reports:customer_quality")

    def make_customer(self, index=1, *, address=True, **overrides):
        fields = {
            "code": f"QA-{index:04d}", "branch": self.branch,
            "document_type": Customer.DocumentType.DNI, "document_number": f"{index:08d}",
            "first_name": "Abonado", "paternal_surname": "Sintético", "phone": "900000001",
        }
        fields.update(overrides)
        customer = Customer.objects.create(**fields)
        if address:
            CustomerAddress.objects.create(customer=customer, address="Calle de prueba 100", district="Distrito de prueba")
        return customer

    def flags(self, customer):
        return customers_with_quality_flags(customer.branch).get(pk=customer.pk)

    def test_complete_customer_has_no_alerts(self):
        customer = self.make_customer()
        self.assertEqual(issues_for(self.flags(customer)), [])
        self.assertEqual(quality_summary(customers_with_quality_flags(self.branch))["flagged"], 0)

    def test_independent_missing_fields_count_customer_once(self):
        customer = self.make_customer(document_number=" ", first_name=" ", paternal_surname="", phone=" ", address=False)
        flagged = self.flags(customer)
        self.assertTrue(flagged.issue_document)
        self.assertTrue(flagged.issue_name)
        self.assertTrue(flagged.issue_address)
        self.assertTrue(flagged.issue_contact)
        self.assertFalse(flagged.issue_duplicate)
        summary = quality_summary(customers_with_quality_flags(self.branch))
        self.assertEqual(summary["flagged"], 1)
        self.assertEqual(sum(summary[key] for key in ("document", "name", "address", "contact")), 4)

    def test_document_formats_and_normalization(self):
        cases = [
            ("DNI", "12345678", False), ("DNI", "1234567X", True),
            ("DNI", "１２３４５６７８", True), ("DNI", " 12345678 ", True),
            ("DNI", "12345678\n", True),
            ("RUC", "20123456789", False), ("RUC", "2012345678", True),
            ("CE", "CE-001", False), ("PASSPORT", "ABC123", False),
            ("PASSPORT", "abc123", True), ("UNKNOWN", "12345678", True),
        ]
        for index, (kind, number, expected) in enumerate(cases, 1):
            with self.subTest(kind=kind, number=number):
                customer = self.make_customer(index, document_type=kind, document_number=number)
                self.assertEqual(self.flags(customer).issue_document, expected)

    def test_duplicates_include_inactive_but_not_other_document_types_or_branches(self):
        first = self.make_customer(document_type="PASSPORT", document_number="AB123")
        second = self.make_customer(2, document_type="PASSPORT", document_number=" ab123 ", is_active=False)
        different_type = self.make_customer(3, document_type="CE", document_number="AB123")
        elsewhere = self.make_customer(4, branch=self.other_branch, document_type="PASSPORT", document_number="Ab123")
        self.assertTrue(self.flags(first).issue_duplicate)
        self.assertTrue(self.flags(second).issue_duplicate)
        self.assertFalse(self.flags(different_type).issue_duplicate)
        self.assertFalse(self.flags(elsewhere).issue_duplicate)
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"issue": "duplicate", "status": "active", "q": first.code})
        self.assertEqual([row["customer"].pk for row in response.context["rows"]], [first.pk])

    def test_blank_documents_are_not_duplicates(self):
        first = self.make_customer(document_number="")
        second = self.make_customer(2, document_number=" ")
        self.assertFalse(self.flags(first).issue_duplicate)
        self.assertFalse(self.flags(second).issue_duplicate)

    def test_inactive_or_incomplete_addresses_do_not_satisfy_check(self):
        customer = self.make_customer(address=False)
        CustomerAddress.objects.create(customer=customer, address="Dirección", district="Distrito", is_active=False)
        CustomerAddress.objects.create(customer=customer, address=" ", district="Distrito")
        CustomerAddress.objects.create(customer=customer, address="Dirección", district=" ")
        self.assertTrue(self.flags(customer).issue_address)
        CustomerAddress.objects.create(customer=customer, address="Otra dirección", district="Distrito", is_primary=False)
        self.assertFalse(self.flags(customer).issue_address)
        self.assertEqual(customers_with_quality_flags(self.branch).count(), 1)

    def test_legal_name_and_alternative_contact(self):
        customer = self.make_customer(person_type="LEGAL", first_name="Representante", business_name=" ", phone="", secondary_phone="900000002")
        self.assertTrue(self.flags(customer).issue_name)
        self.assertFalse(self.flags(customer).issue_contact)
        customer.business_name = "Empresa sintética"
        customer.secondary_phone = ""
        customer.email = "qa@example.invalid"
        customer.save()
        self.assertFalse(self.flags(customer).issue_name)
        self.assertFalse(self.flags(customer).issue_contact)

    def test_branch_scope_and_missing_branch_never_return_all_customers(self):
        own = self.make_customer()
        other = self.make_customer(2, branch=self.other_branch)
        self.assertEqual(list(customers_with_quality_flags(self.branch).values_list("pk", flat=True)), [own.pk])
        self.assertFalse(customers_with_quality_flags(None).exists())
        self.client.force_login(self.user)
        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = self.other_branch.pk
        session.save()
        response = self.client.get(self.url, {"issue": "everyone", "branch": self.branch.pk})
        self.assertEqual([row["customer"].pk for row in response.context["rows"]], [other.pk])
        self.assertEqual(response.context["summary"]["total"], 1)
        with patch("apps.reports.customer_quality_views.get_active_branch", return_value=None):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("rows", response.context)

    def test_permission_and_sidebar_visibility(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        viewer = User.objects.create_user(username="quality-viewer", role=User.Role.TECHNICIAN, branch=self.branch)
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertNotContains(self.client.get(reverse("accounts:profile")), f'href="{self.url}"')
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label="customers", codename="change_customer"))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(self.url), f'href="{self.url}"')
        admin = User.objects.create_user(username="quality-admin", role=User.Role.ADMIN, branch=self.branch)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_filters_summary_pagination_and_escaped_names(self):
        for index in range(1, 28):
            self.make_customer(index, first_name="<script>alert(1)</script>", phone="")
        self.make_customer(28)
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"q": "QA-", "issue": "contact", "status": "active", "page": "2"})
        self.assertEqual(response.context["summary"]["total"], 28)
        self.assertEqual(response.context["summary"]["contact"], 27)
        self.assertEqual(response.context["summary"]["clear"], 1)
        self.assertEqual(response.context["page_obj"].paginator.count, 27)
        self.assertEqual(len(response.context["rows"]), 2)
        self.assertContains(response, "issue=contact&amp;status=active&amp;q=QA-")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        clear = self.client.get(self.url, {"issue": "clear"})
        self.assertEqual(clear.context["page_obj"].paginator.count, 1)
        self.assertEqual(clear.context["rows"][0]["customer"].code, "QA-0028")

    def test_invalid_filters_return_errors_instead_of_empty_success(self):
        self.client.force_login(self.user)
        for params in ({"issue": "unknown"}, {"status": "unknown"}, {"q": "x" * 121}):
            response = self.client.get(self.url, params)
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.context["form"].errors)
            self.assertNotIn("rows", response.context)

    def test_read_only_response_and_no_per_customer_queries(self):
        customer = self.make_customer(phone="")
        before = Customer.objects.values().get(pk=customer.pk)
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.post(self.url, {"phone": "999999999"}).status_code, 405)
        self.assertEqual(Customer.objects.values().get(pk=customer.pk), before)
        for index in range(2, 8):
            self.make_customer(index)
        with self.assertNumQueries(1):
            rows = list(customers_with_quality_flags(self.branch)[:25])
            for row in rows:
                str(row)
                issues_for(row)
