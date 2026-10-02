import io
import json
import os
import re
import tempfile
from functools import partial
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.customers.qa_billing_examples import BILLING_SAMPLE_ROUTE, prepare_billing_examples
from apps.customers.qa_samples import prepare_customer_samples
from apps.payments.invoicing import receipt_totals
from apps.payments import pdf
from apps.payments.models import Charge, Payment, Receipt, ReceiptSequence
from apps.payments.tests.base import PaymentsTestCase
from apps.services.models import Subscription


@patch.dict(os.environ, {"WEBSITE_SITE_NAME": "sicv-telecable-qa"})
class CustomerQABillingExamplesTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()
        self.cashier.is_superuser = True
        self.cashier.save(update_fields=["is_superuser"])
        self.subscription.status = Subscription.Status.PRESALE
        self.subscription.save(update_fields=["status"])

    def prepare(self):
        return prepare_billing_examples(customer_code=self.customer.code, actor=self.cashier, day=date(2026, 10, 2))

    def test_cases_use_confirmed_rules_without_changing_subscription(self):
        data, created = self.prepare()
        self.assertTrue(created)
        self.assertEqual([len(data[key]) for key in ("cases", "charges", "payments", "receipts")], [8, 10, 6, 6])
        charges = [Charge.objects.get(pk=pk) for pk in data["charges"]]
        self.assertTrue(all(c.subscription_id is None and not c.auto_update for c in charges))
        first = charges[0]
        self.assertEqual((first.coverage_start, first.period_end, first.due_date, first.discount_deadline),
                         (date(2026, 8, 14), date(2026, 9, 13), date(2026, 9, 13), date(2026, 9, 10)))
        self.assertEqual(first.balance_on(date(2026, 10, 2)), Decimal("0.00"))
        self.assertEqual(list(first.components.order_by("pk").values_list("amount", flat=True)), [Decimal("81.50"), Decimal("7.50")])
        payments = [Payment.objects.get(pk=pk) for pk in data["payments"]]
        self.assertEqual([p.amount for p in payments], [Decimal(x) for x in ("79", "89", "104", "84", "89", "104")])
        self.assertEqual([sum((a.discount for a in p.allocations.all()), Decimal("0")) for p in payments], [Decimal(x) for x in ("10", "0", "0", "5", "0", "0")])
        self.assertEqual(payments[-1].status, Payment.Status.PENDING)
        self.assertEqual(sum((a.charge.balance for a in payments[-1].allocations.all()), Decimal("0")), Decimal("104"))
        for receipt in Receipt.objects.filter(pk__in=data["receipts"]):
            self.assertEqual(receipt_totals(receipt)["total"], receipt.payment.amount)
        partial = Charge.objects.get(pk=data["cases"][5]["charges"][0])
        self.assertEqual((partial.coverage_start, partial.period_end, partial.amount), (date(2026, 5, 7), date(2026, 5, 31), Decimal("74.25")))
        self.subscription.refresh_from_db()
        self.assertEqual((self.subscription.status, self.subscription.base_monthly_fee), (Subscription.Status.PRESALE, Decimal("80")))
        self.assertEqual(Subscription.objects.count(), 1)

    def test_rerun_preserves_confirmed_payments_and_previous_samples(self):
        old, _ = prepare_customer_samples(customer_code=self.customer.code, actor=self.cashier, day=date(2026, 10, 2))
        original, _ = self.prepare()
        pending = Payment.objects.get(pk=original["payments"][-1])
        pending.confirm(actor=self.cashier)
        self.cashier.is_active = False
        self.cashier.save(update_fields=["is_active"])
        repeated, created = self.prepare()
        self.assertFalse(created)
        self.assertEqual(repeated, original)
        self.assertEqual((Charge.objects.count(), Payment.objects.count(), Receipt.objects.count()), (14, 9, 9))
        self.assertEqual(Payment.objects.get(pk=pending.pk).status, Payment.Status.REGISTERED)
        self.assertEqual(Charge.objects.get(pk=old["charges"][2]).balance, Decimal("80.00"))
        self.assertEqual(AuditEvent.objects.filter(route_name=BILLING_SAMPLE_ROUTE).count(), 1)

    def test_failure_and_production_guard_leave_no_records(self):
        with patch.dict(os.environ, {"WEBSITE_SITE_NAME": "sicv-production"}):
            with self.assertRaises(ValidationError):
                self.prepare()
        with patch("apps.payments.services.register_payment", side_effect=ValidationError("Error simulado")):
            with self.assertRaises(ValidationError):
                self.prepare()
        self.assertFalse(Charge.objects.exists())
        self.assertFalse(ReceiptSequence.objects.filter(code="QA-MUESTRAS-HYO").exists())
        self.assertFalse(AuditEvent.objects.filter(route_name=BILLING_SAMPLE_ROUTE).exists())

    def test_command_reports_billing_counts_without_customer_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.json"
            call_command("preparar_muestras_abonado_qa", customer_code=self.customer.code,
                         actor=self.cashier.username, billing_examples=True, status_output=str(path), stdout=io.StringIO())
            data = json.loads(path.read_text())
        self.assertEqual(data["billing_examples"], {"prepared": True, "created": True, "cases": 8, "charges": 10, "payments": 6, "receipts": 6})
        self.assertNotIn(self.customer.code, json.dumps(data))
        self.assertNotIn(self.customer.document_number, json.dumps(data))

    def test_presentation_panel_and_both_pdf_formats_keep_the_same_receipt(self):
        data, _ = self.prepare()
        self.login(self.cashier)
        response = self.client.get(reverse("payments:receipts", kwargs={"pk": self.customer.pk}))
        self.assertContains(response, "Ejemplos de facturación para presentación")
        self.assertContains(response, "Corte simulado")
        self.assertContains(response, "Vertical")
        self.assertContains(response, "Horizontal")
        receipt = Receipt.objects.get(pk=data["receipts"][0])
        sequence_number = receipt.sequence.last_number
        for format_name in ReceiptSequence.PrintFormat.values:
            with self.subTest(format_name=format_name):
                response = self.client.get(reverse("payments:receipt_pdf", kwargs={"pk": receipt.pk}), {"ver": "1", "formato": format_name})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response["Content-Disposition"].startswith("inline;"))
                payload = b"".join(response.streaming_content)
                self.assertEqual(payload.count(b"/Type /Page\n"), 1)
                box = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)", payload)
                self.assertIsNotNone(box)
                width, height = map(float, box.groups())
                if format_name == ReceiptSequence.PrintFormat.TICKET:
                    self.assertLess(width, height)
                    self.assertAlmostEqual(width, 80 * 72 / 25.4, places=2)
                else:
                    self.assertGreater(width, height)
        response = self.client.get(reverse("payments:receipt_pdf", kwargs={"pk": receipt.pk}), {"formato": "INVALID"})
        self.assertEqual(response.status_code, 400)
        receipt.sequence.refresh_from_db()
        self.assertEqual(receipt.sequence.last_number, sequence_number)
        self.assertEqual(Receipt.objects.count(), 6)
        self.assertEqual(receipt_totals(receipt)["total"], Decimal("79.00"))

    def test_pending_pdf_is_identified_and_sample_has_no_sunat_verification_invitation(self):
        data, _ = self.prepare()
        receipt = Receipt.objects.get(pk=data["receipts"][-1])
        self.assertIn("No enviada a SUNAT", pdf._leyenda(receipt))
        original = pdf.SimpleDocTemplate
        for format_name in ReceiptSequence.PrintFormat.values:
            stream = io.BytesIO()
            with patch.object(pdf, "SimpleDocTemplate", partial(original, pageCompression=0)):
                pdf.render_receipt(receipt, stream, print_format=format_name)
            self.assertIn(b"PAGO PENDIENTE DE CONFIRMACI", stream.getvalue())
            self.assertNotIn(b"www.sunat.gob.pe", stream.getvalue())
            self.assertEqual(stream.getvalue().count(b"/Type /Page\n"), 1)
            if format_name == ReceiptSequence.PrintFormat.SHEET:
                self.assertIn(b"10:00:00", stream.getvalue())
