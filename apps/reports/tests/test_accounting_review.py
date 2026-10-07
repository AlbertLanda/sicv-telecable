"""La revisión QA permite opinar sin otorgar acceso operativo ni emitir."""
import csv
import io
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.customers.models import Customer
from apps.customers.qa_billing_examples import BILLING_SAMPLE_ROUTE
from apps.fiscal.models import FiscalDocument
from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch
from apps.payments.models import Charge, Payment, Receipt
from apps.reports.accounting_review_catalog import CASES, CATALOG_VERSION
from apps.reports.models import AccountingReviewNote


@override_settings(ACCOUNTING_REVIEW_ENABLED=True)
class AccountingReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(code="REVIEW-QA", name="Sede de prueba")
        cls.accountant = User.objects.create_user(username="qa-contabilidad", role=User.Role.ACCOUNTING,
                                                  branch=cls.branch)
        cls.other = User.objects.create_user(username="qa-otra-revision", role=User.Role.ACCOUNTING,
                                             branch=cls.branch)
        cls.admin = User.objects.create_user(username="qa-supervisor", role=User.Role.ADMIN, branch=cls.branch)
        cls.technician = User.objects.create_user(username="qa-tecnico", role=User.Role.TECHNICIAN,
                                                  branch=cls.branch)
        cls.url = reverse("reports:accounting_review")

    def setUp(self):
        self.client.force_login(self.accountant)

    def submit(self, code="abonado", **overrides):
        data = {"catalog_version": CATALOG_VERSION, "status": "CHANGES",
                "missing_data": "Código antiguo", "note": "Mostrar la referencia del sistema anterior."}
        data.update(overrides)
        return self.client.post(self.url + "?caso=" + code, data)

    def test_accountant_can_read_every_example_without_operational_permissions(self):
        for item in CASES:
            with self.subTest(case=item["code"]):
                response = self.client.get(self.url, {"caso": item["code"]})
                self.assertContains(response, item["title"])
                self.assertContains(response, item["expected"])
                self.assertContains(response, "sin validez tributaria")
                self.assertEqual(response["Cache-Control"], "private, no-store")
        for perm in ("customers.change_customer", "payments.add_payment", "payments.view_receipt",
                     "payments.void_payment", "fiscal.add_fiscaldocument"):
            self.assertFalse(self.accountant.has_perm(perm))
        self.assertEqual(len(CASES), 16)
        self.assertEqual(len({item["code"] for item in CASES}), 16)
        self.assertEqual(AccountingReviewNote.objects.count(), 0)

    def test_save_resume_and_history_do_not_change_financial_records(self):
        models = (Customer, Charge, Payment, Receipt, FiscalDocument)
        before = [model.objects.count() for model in models]
        response = self.submit()
        self.assertRedirects(response, self.url + "?caso=abonado")
        self.client.logout()
        self.client.force_login(self.accountant)
        response = self.client.get(self.url)
        self.assertEqual(response.context["form"].initial["missing_data"], "Código antiguo")
        self.assertEqual(response.context["reviewed_count"], 1)
        self.assertEqual(response.context["changes_count"], 1)
        self.assertEqual(response.context["pending_count"], 15)
        self.submit(status="REVIEWED", missing_data="", note="Revisado el ejemplo.")
        response = self.client.get(self.url)
        self.assertEqual(response.context["changes_count"], 0)
        self.assertEqual(response.context["reviewed_count"], 1)
        self.assertEqual(len(response.context["history"]), 2)
        self.assertEqual(AccountingReviewNote.objects.count(), 2)
        self.assertEqual([model.objects.count() for model in models], before)

    def test_mark_pending_and_not_applicable(self):
        self.submit(status="NOT_APPLICABLE", note="Este caso no se usa en la operación.", missing_data="")
        self.assertEqual(self.client.get(self.url).context["reviewed_count"], 1)
        self.submit(status="PENDING", note="Consultar al área.", missing_data="")
        self.assertEqual(self.client.get(self.url).context["pending_count"], 16)

    def test_required_explanation_lengths_and_catalog_version(self):
        for data in ({"note": " "}, {"status": "NOT_APPLICABLE", "note": ""},
                     {"status": "REVIEWED"}, {"status": "APPROVED"},
                     {"catalog_version": 0}, {"catalog_version": 99},
                     {"missing_data": "x" * 501}, {"note": "x" * 2001}):
            with self.subTest(data=data):
                response = self.submit(**data)
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.context["form"].errors)
        self.assertEqual(AccountingReviewNote.objects.count(), 0)

    def test_invalid_case_and_export_fail_closed(self):
        for query in ({"caso": "unknown"}, {"caso": "../abonado"}, {"export": "xlsx"}):
            self.assertEqual(self.client.get(self.url, query).status_code, 404)
        self.assertEqual(self.submit("unknown").status_code, 404)
        self.assertEqual(AccountingReviewNote.objects.count(), 0)

    def test_qaguard_blocks_read_write_and_exports_even_superuser(self):
        self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        with override_settings(ACCOUNTING_REVIEW_ENABLED=False):
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.assertEqual(self.client.get(self.url, {"export": "csv"}).status_code, 404)
            self.assertEqual(self.submit().status_code, 404)
            self.assertNotContains(self.client.get(reverse("accounts:profile")), f'href="{self.url}"')
        self.assertEqual(AccountingReviewNote.objects.count(), 0)

    def test_login_permission_and_sidebar(self):
        self.assertContains(self.client.get(self.url), f'href="{self.url}"')
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.submit().status_code, 302)
        self.client.force_login(self.technician)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.submit().status_code, 403)
        self.assertNotContains(self.client.get(reverse("accounts:profile")), f'href="{self.url}"')

    def test_reviewer_isolation_on_read_export_and_write(self):
        self.submit()
        self.client.force_login(self.other)
        response = self.client.get(self.url)
        self.assertEqual(response.context["reviewed_count"], 0)
        self.assertNotContains(response, "Mostrar la referencia del sistema anterior.")
        for query in ({"revisor": self.accountant.pk}, {"revisor": self.accountant.pk, "export": "csv"}):
            self.assertEqual(self.client.get(self.url, query).status_code, 403)
        response = self.client.post(self.url + f"?revisor={self.accountant.pk}",
                                    {"status": "REVIEWED", "catalog_version": CATALOG_VERSION})
        self.assertEqual(response.status_code, 403)
        self.submit(reviewer=self.accountant.pk, reviewer_id=self.accountant.pk)
        self.assertEqual(AccountingReviewNote.objects.first().reviewer, self.other)

    def test_supervisor_reads_history_and_exports_but_cannot_impersonate(self):
        self.submit()
        self.submit(note="Segunda revisión de prueba.")
        self.client.force_login(self.admin)
        response = self.client.get(self.url, {"revisor": self.accountant.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["own_review"])
        self.assertContains(response, "Segunda revisión de prueba.")
        self.assertNotContains(response, '<button type="submit" class="tc-btn tc-btn-primary">')
        self.assertEqual(self.client.get(self.url, {"revisor": self.accountant.pk, "export": "csv"}).status_code, 200)
        self.assertEqual(self.client.post(self.url + f"?revisor={self.accountant.pk}", {}).status_code, 403)
        for value in ("invalid", "999999999999999999999999", "0"):
            self.assertEqual(self.client.get(self.url, {"revisor": value}).status_code, 404)

    def test_csv_includes_unreviewed_cases_and_neutralizes_formulas(self):
        self.submit(missing_data="=1+1", note="@SUM(1+1)")
        response = self.client.get(self.url, {"export": "csv"})
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("attachment", response["Content-Disposition"])
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[0]["Dato faltante"], "'=1+1")
        self.assertEqual(rows[0]["Observación"], "'@SUM(1+1)")
        self.assertEqual(rows[1]["Estado"], "Pendiente de revisar")
        self.assertIn("DNI-DEMO", rows[0]["Datos del ejemplo"])
        self.assertIn("Resultado esperado", rows[0])
        self.assertEqual(rows[0]["Revisor"], self.accountant.username)

    def test_comments_are_escaped_and_csrf_is_required(self):
        self.submit(note='<script>alert("demo")</script>')
        response = self.client.get(self.url)
        self.assertNotContains(response, '<script>alert("demo")</script>')
        self.assertContains(response, "&lt;script&gt;")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.accountant)
        self.assertEqual(csrf_client.post(self.url, {"status": "REVIEWED", "catalog_version": CATALOG_VERSION}).status_code, 403)
        self.assertEqual(AccountingReviewNote.objects.count(), 1)

    def test_live_links_require_customer_receipt_permissions_and_active_branch(self):
        customer = Customer.objects.create(code="REVIEW-DEMO", branch=self.branch, first_name="Ejemplo",
                                            paternal_surname="Sintético", document_number="11111111")
        AuditEvent.objects.create(actor=self.admin, branch=self.branch, method="COMMAND", route_name=BILLING_SAMPLE_ROUTE,
                                  path=f"/customers/{customer.pk}/", description="Muestra de prueba", changes={})
        self.assertEqual(self.client.get(self.url).context["sample_links"], [])
        self.client.force_login(self.admin)
        links = self.client.get(self.url).context["sample_links"]
        self.assertEqual(links[0]["url"], reverse("payments:receipts", kwargs={"pk": customer.pk}))
        other_branch = Branch.objects.create(code="REVIEW-OTHER", name="Otra sede sintética")
        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = other_branch.pk
        session.save()
        self.assertEqual(self.client.get(self.url).context["sample_links"], [])
        with patch("apps.organization.context_processors.get_active_branch", return_value=None):
            self.assertEqual(self.client.get(self.url).context["sample_links"], [])

    def test_user_with_only_review_permission_cannot_supervise(self):
        self.technician.user_permissions.add(Permission.objects.get(
            content_type__app_label="payments", codename="view_cash_closing"))
        self.client.force_login(self.technician)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.get(self.url, {"revisor": self.accountant.pk}).status_code, 403)
