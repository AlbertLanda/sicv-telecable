import io
import json
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.customers.qa_samples import SAMPLE_ROUTE, SAMPLE_TITLE, prepare_customer_samples
from apps.payments.models import Charge, Payment, Receipt, ReceiptSequence
from apps.payments.tests.base import PaymentsTestCase
from apps.services.models import Subscription
from apps.work_orders.models import OrderType, WorkOrder


@patch.dict(os.environ, {"WEBSITE_SITE_NAME": "sicv-telecable-qa"})
class CustomerQASamplesTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()
        self.cashier.is_superuser = True
        self.cashier.save(update_fields=["is_superuser"])
        self.subscription.status = Subscription.Status.PRESALE
        self.subscription.save(update_fields=["status"])
        incident, _ = OrderType.objects.get_or_create(code="INCIDENT", defaults={"name": "Incidencia"})
        incident.is_active = True
        incident.save(update_fields=["is_active"])
        installation, _ = OrderType.objects.get_or_create(code="INSTALLATION", defaults={"name": "Instalación"})
        self.installation = WorkOrder.objects.create(
            order_number="OT-EXISTENTE", subscription=self.subscription,
            order_type=installation, branch=self.branch, created_by=self.cashier,
        )
        self.official_sequence = ReceiptSequence.objects.create(
            code="OFICIAL", series="B001", last_number=7, is_active=True,
        )

    def prepare(self):
        return prepare_customer_samples(customer_code=self.customer.code, actor=self.cashier, day=date(2026, 10, 2))

    def test_samples_show_full_payments_and_preserve_installation(self):
        data, created = self.prepare()
        self.assertTrue(created)
        self.assertEqual([len(data[key]) for key in ("charges", "payments", "receipts", "orders")], [4, 3, 3, 1])
        charges = [Charge.objects.get(pk=pk) for pk in data["charges"]]
        self.assertEqual([charge.balance for charge in charges], [Decimal("0"), Decimal("80"), Decimal("80"), Decimal("25")])
        self.assertTrue(all(charge.subscription_id is None for charge in charges))
        self.assertTrue(all("MUESTRA QA" in charge.description for charge in charges))
        self.assertEqual(list(Payment.objects.order_by("pk").values_list("status", flat=True)), [Payment.Status.REGISTERED, Payment.Status.PENDING, Payment.Status.VOIDED])
        for payment in Payment.objects.all():
            self.assertEqual(payment.amount, sum(allocation.amount for allocation in payment.allocations.all()))
        self.subscription.refresh_from_db()
        self.installation.refresh_from_db()
        self.official_sequence.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.PRESALE)
        self.assertEqual(self.installation.status, WorkOrder.Status.PENDING)
        self.assertIsNone(self.installation.assigned_technician_id)
        self.assertEqual(self.official_sequence.last_number, 7)
        self.assertEqual(WorkOrder.objects.get(pk=data["orders"][0]).status, WorkOrder.Status.CANCELLED)
        sequence = ReceiptSequence.objects.get(code="QA-MUESTRAS-HYO")
        self.assertEqual(sequence.document_title, SAMPLE_TITLE)
        self.assertFalse(sequence.is_active)
        self.assertIsNone(sequence.issuer_id)
        self.assertEqual(sequence.last_number, 3)
        self.assertEqual(AuditEvent.objects.filter(route_name=SAMPLE_ROUTE).count(), 1)

    def test_repeated_startup_keeps_user_changes(self):
        original, _ = self.prepare()
        Payment.objects.get(pk=original["payments"][1]).confirm(actor=self.cashier)
        self.cashier.is_active = False
        self.cashier.save(update_fields=["is_active"])
        repeated, created = self.prepare()
        self.assertFalse(created)
        self.assertEqual(repeated, original)
        self.assertEqual(Charge.objects.count(), 4)
        self.assertEqual(Payment.objects.count(), 3)
        self.assertEqual(Receipt.objects.count(), 3)
        self.assertEqual(WorkOrder.objects.count(), 2)
        self.assertEqual(Payment.objects.get(pk=original["payments"][1]).status, Payment.Status.REGISTERED)

    def test_existing_debt_is_not_paid_by_samples(self):
        from apps.payments.services import create_manual_charge
        original = create_manual_charge(
            customer=self.customer, concept=Charge.Concept.OTHER,
            description="Cargo previo", amount=Decimal("40.00"),
            due_date=date(2026, 9, 1), auto_update=False,
        )
        self.prepare()
        original.refresh_from_db()
        self.assertEqual(original.balance, Decimal("40.00"))
        self.assertEqual(original.description, "Cargo previo")
        self.assertFalse(original.allocations.exists())

    def test_failure_rolls_back_all_samples_and_counter(self):
        with patch("apps.work_orders.services.create_incident_work_order", side_effect=ValidationError("Catálogo ausente")):
            with self.assertRaises(ValidationError):
                self.prepare()
        self.assertEqual(Charge.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(Receipt.objects.count(), 0)
        self.assertEqual(WorkOrder.objects.count(), 1)
        self.assertFalse(ReceiptSequence.objects.filter(code="QA-MUESTRAS-HYO").exists())
        self.assertFalse(AuditEvent.objects.filter(route_name=SAMPLE_ROUTE).exists())

    def test_production_and_unauthorized_actor_cannot_seed(self):
        with patch.dict(os.environ, {"WEBSITE_SITE_NAME": "sicv-production"}):
            with self.assertRaises(ValidationError):
                self.prepare()
            with self.assertRaises(CommandError):
                call_command("preparar_muestras_abonado_qa", customer_code=self.customer.code, actor=self.cashier.username, stdout=io.StringIO())
        self.cashier.is_superuser = False
        self.cashier.save(update_fields=["is_superuser"])
        with self.assertRaises(ValidationError):
            self.prepare()
        self.assertEqual(Charge.objects.count(), 0)

    def test_command_produces_public_counts_without_customer_data(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "status.json"
            call_command("preparar_muestras_abonado_qa", customer_code=self.customer.code, actor=self.cashier.username, status_output=str(output), stdout=io.StringIO())
            status = json.loads(output.read_text())
        self.assertEqual(status, {"sample": "customer_tabs_v1", "prepared": True, "created": True, "charges": 4, "payments": 3, "receipts": 3, "orders": 1})

    def test_absent_customer_skips_without_creating_records(self):
        call_command("preparar_muestras_abonado_qa", customer_code="NO-EXISTE", actor="NO-EXISTE", if_present=True, stdout=io.StringIO())
        self.assertEqual(Charge.objects.count(), 0)

    def test_sample_tabs_and_receipt_pdf_render(self):
        data, _ = self.prepare()
        self.login(self.cashier)
        for route in ("customers:detail", "customers:orders", "customers:activity", "payments:debt", "payments:history", "payments:receipts"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route, kwargs={"pk": self.customer.pk}))
                self.assertContains(response, "Muestras de QA")
        for pk in data["receipts"]:
            response = self.client.get(reverse("payments:receipt_detail", kwargs={"pk": pk}))
            self.assertContains(response, SAMPLE_TITLE)
            response = self.client.get(reverse("payments:receipt_pdf", kwargs={"pk": pk}))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF"))
