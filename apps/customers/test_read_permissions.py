from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.organization.models import Branch
from .models import Customer


class CustomerReadPermissionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(code="QA-READ-A", name="Sede prueba A")
        other = Branch.objects.create(code="QA-READ-B", name="Sede prueba B")
        cls.customer = Customer.objects.create(code="QA-READ-1", branch=other,
            document_type="DNI", document_number="00000007", first_name="Abonado ficticio")

    def urls(self):
        return [reverse("customers:search")] + [reverse("customers:" + name, args=[self.customer.pk])
            for name in ("detail", "orders", "activity", "use", "work_order_ui_preview")]

    def test_operational_roles_cannot_open_customer_data_without_permission(self):
        for role in ("TECHNICIAN", "WAREHOUSE", "ACCOUNTING", "SALES", "RETENTION", "SUPERVISOR"):
            user = User.objects.create_user(username=role, role=role, branch=self.branch)
            self.client.force_login(user)
            for url in self.urls():
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
            self.assertNotIn("selected_customer_id", self.client.session)

    def test_atc_admin_noc_keep_authorized_cross_branch_reads(self):
        for role in ("ATC", "ADMIN", "NOC"):
            user = User.objects.create_user(username=role, role=role, branch=self.branch)
            self.client.force_login(user)
            response = self.client.get(reverse("customers:detail", args=[self.customer.pk]))
            self.assertContains(response, "Abonado ficticio")

    def test_explicit_read_permission_and_anonymous_redirect(self):
        url = reverse("customers:detail", args=[self.customer.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        user = User.objects.create_user(username="read_grant", role="SUPERVISOR")
        user.user_permissions.add(Permission.objects.get(content_type__app_label="customers", codename="view_customer"))
        self.client.force_login(user)
        self.assertEqual(self.client.get(url).status_code, 200)
