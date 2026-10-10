from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User
from apps.payments.models import Issuer, Payment, PaymentAllocation, Receipt, ReceiptSequence, Charge
from apps.payments.tests.base import PaymentsTestCase
from .erp_links import receipt_links
from .models import CompanyAccess, Document, ImportBatch


class ErpLinksTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.make_user("erp_admin", role=User.Role.ADMIN)
        self.issuer = Issuer.objects.create(code="ERP-QA", business_name="Empresa de prueba", ruc="20999999991")
        self.access = CompanyAccess.objects.create(user=self.cashier, issuer=self.issuer, updated_by=self.admin)
        self.batch = ImportBatch.objects.create(issuer=self.issuer, issuer_ruc=self.issuer.ruc,
            period=date(2026, 9, 1), source="RVIE", filename="ficticio.csv", sha256="1" * 64,
            document_count=1, line_count=0, imported_by=self.admin)
        self.doc = Document.objects.create(batch=self.batch, document_type="03", series="BQA1", number="1",
            issue_date=date(2026, 9, 1), receiver_document=self.customer.document_number,
            receiver_name="Cliente de prueba", total=118, sire_state="1")
        self.sequence = ReceiptSequence.objects.create(code="ERP-QA", series="BQA1", issuer=self.issuer,
            label="Talonario ficticio", sunat_code="03")
        self.receipt = self.make_receipt(self.sequence)
        charge = Charge.objects.create(customer=self.customer, subscription=self.subscription, description="Plan ficticio",
            amount=118, due_date=date(2026, 9, 1), concept=Charge.Concept.OTHER)
        PaymentAllocation.objects.create(payment=self.receipt.payment, charge=charge, amount=118)

    def make_receipt(self, sequence):
        payment = Payment.objects.create(customer=self.customer, branch=self.branch, received_by=self.admin,
            method=Payment.Method.CASH, status=Payment.Status.PENDING, amount=118)
        return Receipt.objects.create(payment=payment, sequence=sequence, series="BQA1", number=1)

    def link(self):
        return receipt_links(user=self.cashier, issuer=self.issuer, documents=[self.doc])[self.doc.key]

    def test_exact_key_shows_customer_service_and_distinct_payment_state(self):
        link = self.link()
        self.assertEqual(link["status"], "LINKED")
        self.assertEqual(link["customer_code"], self.customer.code)
        self.assertIn("Plan ficticio", link["services"])
        self.assertEqual(link["service_branches"], self.branch.name)
        self.assertEqual(link["payment_state"], "Pendiente de cobro")
        self.assertEqual(link["fiscal_state"], "No acreditado por este cruce")
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.sire_state, "1")
        self.receipt.payment.status = Payment.Status.VOIDED
        self.receipt.payment.save(update_fields=["status"])
        self.assertEqual(self.link()["payment_state"], "Cobro anulado")

    def test_same_number_other_company_or_document_type_does_not_match(self):
        other = Issuer.objects.create(code="ERP-OTHER", business_name="Otra", ruc="20999999992")
        self.sequence.issuer = other
        self.sequence.save()
        self.assertEqual(self.link()["status"], "MISSING")
        self.sequence.issuer = self.issuer
        self.sequence.sunat_code = "14"
        self.sequence.save()
        self.assertEqual(self.link()["status"], "MISSING")

    def test_ambiguous_keys_and_receiver_conflicts_never_choose_a_customer(self):
        self.doc.receiver_document = "00000002"
        self.assertEqual(self.link()["status"], "CONFLICT")
        self.assertNotIn("customer_id", self.link())
        self.doc.receiver_document = self.customer.document_number
        duplicate = ReceiptSequence.objects.create(code="ERP-DUP", issuer=self.issuer, series="BQA1", sunat_code="03")
        self.make_receipt(duplicate)
        self.assertEqual(self.link()["status"], "AMBIGUOUS")
        self.assertNotIn("customer_id", self.link())

    def test_large_number_missing_identity_and_amount_difference_are_safe(self):
        self.doc.number = "99999999999999999999"
        self.assertEqual(self.link()["status"], "MISSING")
        self.doc.number = "1"
        self.doc.receiver_document = ""
        self.doc.total = Decimal("119")
        self.assertEqual(len(self.link()["warnings"]), 2)

    def test_batch_lookup_does_not_query_per_imported_document(self):
        docs = [self.doc] + [Document(batch=self.batch, document_type="03", series="BQA1", number=str(number),
            issue_date=date(2026, 9, 1), total=118) for number in range(2, 151)]
        with CaptureQueriesContext(connection) as queries:
            links = receipt_links(user=self.cashier, issuer=self.issuer, documents=docs)
        self.assertEqual(len(links), 150)
        self.assertLessEqual(len(queries), 10)

    def test_documents_from_another_issuer_are_refused_even_with_valid_keys(self):
        self.batch.issuer_ruc = "20999999992"
        self.batch.save(update_fields=["issuer_ruc"])
        with self.assertRaises(PermissionDenied):
            self.link()

    def test_scope_search_and_accounting_does_not_get_customer_ficha_access(self):
        self.client.force_login(self.cashier)
        params = {"issuer": self.issuer.pk, "period": "2026-09", "q": self.customer.code}
        page = self.client.get(reverse("accounting:workspace"), params)
        self.assertContains(page, self.customer.code)
        self.assertNotContains(page, "Abrir ficha del abonado")
        self.assertEqual(self.client.get(reverse("customers:detail", args=[self.customer.pk])).status_code, 403)
        self.access.enabled = False
        self.access.save()
        with self.assertRaises(PermissionDenied):
            self.link()
        self.assertEqual(self.client.get(reverse("accounting:workspace"), params).status_code, 400)
