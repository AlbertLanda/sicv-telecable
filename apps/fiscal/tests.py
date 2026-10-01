"""Borradores sin efectos de caja/fiscales y validación diferida segura."""

from datetime import date
from decimal import Decimal
import uuid

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from unittest.mock import patch

from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch
from apps.payments.models import Charge, Issuer, Payment, Receipt, ReceiptSequence
from apps.payments.tests.base import PaymentsTestCase
from .admin import FiscalDocumentAdmin, FiscalEventAdmin, FiscalProfileRevisionAdmin
from .forms import FiscalProfileForm
from .models import DocumentType, FiscalDocument, FiscalEvent, FiscalProfile, FiscalProfileRevision
from .services import cancel_draft, prepare_draft, save_profile, submit_document


class FiscalFoundationTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()
        self.issuer = Issuer.objects.create(code="TEST", business_name="Empresa de prueba", ruc="20123456789")
        self.cashier.user_permissions.add(*Permission.objects.filter(content_type__app_label="fiscal"))
        self.charge = self.make_charge()

    def make_charge(self, **overrides):
        values = dict(customer=self.customer, concept=Charge.Concept.OTHER,
                      description="Servicio de prueba", amount=Decimal("80.00"),
                      early_discount=Decimal("5.00"), discount_deadline=date(2026, 10, 10),
                      due_date=date(2026, 10, 31))
        values.update(overrides)
        return Charge.objects.create(**values)

    def prepare(self, **overrides):
        values = dict(actor=self.cashier, branch=self.branch, customer_id=self.customer.pk,
                      issuer_id=self.issuer.pk, document_type=DocumentType.SALES_RECEIPT,
                      charge_ids=[self.charge.pk], proposed_issue_date=date(2026, 10, 1), request_key=uuid.uuid4())
        values.update(overrides)
        return prepare_draft(**values)

    def open_session(self, user=None):
        self.client.force_login(user or self.cashier)
        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = self.branch.pk
        session.save()

    def test_draft_neither_collects_money_nor_changes_debt_or_numbering(self):
        counters = list(ReceiptSequence.objects.values())
        payment_count, receipt_count = Payment.objects.count(), Receipt.objects.count()
        original = Charge.objects.values().get(pk=self.charge.pk)
        document = self.prepare()
        self.assertEqual(document.source_total, Decimal("80.00"))
        self.assertEqual(document.status, FiscalDocument.Status.DRAFT)
        self.assertEqual(Charge.objects.values().get(pk=self.charge.pk), original)
        self.assertEqual(Payment.objects.count(), payment_count)
        self.assertEqual(Receipt.objects.count(), receipt_count)
        self.assertEqual(list(ReceiptSequence.objects.values()), counters)
        self.assertIn("Impuestos y descuentos fiscales sin calcular", document.snapshot["limitations"])
        self.assertEqual(document.snapshot["lines"][0]["early_discount"], "5.00")

    def test_original_amount_is_separate_from_paid_balance(self):
        from apps.payments.services import register_payment
        register_payment(customer=self.customer, amount=Decimal("80.00"), method=Payment.Method.CASH,
                         branch=self.branch, user=self.cashier, allocations=[(self.charge, Decimal("80.00"))],
                         day=date(2026, 10, 20))
        self.assertEqual(self.prepare().source_total, Decimal("80.00"))

    def test_snapshot_survives_source_customer_issuer_and_charge_changes(self):
        document = self.prepare()
        snapshot = document.snapshot
        self.issuer.business_name = "Empresa corregida"
        self.issuer.save()
        self.customer.first_name = "Nombre corregido"
        self.customer.save()
        self.charge.amount = Decimal("99.00")
        self.charge.save()
        document.refresh_from_db()
        self.assertEqual(document.snapshot, snapshot)
        self.assertEqual(document.source_total, Decimal("80.00"))
        self.open_session()
        response = self.client.get(reverse("fiscal:detail", args=[document.public_id]))
        self.assertContains(response, "Empresa de prueba")
        self.assertNotContains(response, "Empresa corregida")
        self.assertNotContains(response, "Nombre corregido")

    def test_double_submission_returns_same_document_and_single_event(self):
        key = uuid.uuid4()
        first = self.prepare(request_key=key)
        second = self.prepare(request_key=key)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(FiscalDocument.objects.count(), 1)
        self.assertEqual(FiscalEvent.objects.count(), 1)

    def test_reused_request_key_with_other_data_is_rejected(self):
        key = uuid.uuid4()
        self.prepare(request_key=key)
        with self.assertRaisesMessage(ValidationError, "otros datos"):
            self.prepare(request_key=key, proposed_issue_date=date(2026, 10, 2))

    def test_missing_duplicate_foreign_and_cancelled_charges_are_rejected(self):
        other = self.make_charge(status=Charge.Status.CANCELLED)
        for ids in ([], [self.charge.pk, self.charge.pk], [999999], [other.pk]):
            with self.subTest(ids=ids), self.assertRaises(ValidationError):
                self.prepare(charge_ids=ids)
        self.assertFalse(FiscalDocument.objects.exists())

    def test_foreign_customer_charge_is_rejected(self):
        from apps.customers.models import Customer
        other_customer = Customer.objects.create(code="OTHER", branch=self.branch, document_type="DNI", document_number="00000002")
        charge = self.make_charge(customer=other_customer)
        with self.assertRaises(ValidationError):
            self.prepare(charge_ids=[charge.pk])

    def test_mixed_currencies_are_rejected(self):
        other = self.make_charge(currency="USD")
        with self.assertRaisesMessage(ValidationError, "monedas"):
            self.prepare(charge_ids=[self.charge.pk, other.pk])

    def test_inactive_issuer_is_rejected(self):
        self.issuer.is_active = False
        self.issuer.save()
        with self.assertRaises(ValidationError):
            self.prepare()

    def test_service_enforces_permission_and_branch(self):
        user = self.make_user("sin-permiso-fiscal")
        with self.assertRaises(PermissionDenied):
            self.prepare(actor=user)
        other_branch = Branch.objects.create(code="OTHER", name="Otra sede")
        with self.assertRaises(ValidationError):
            self.prepare(branch=other_branch)

    def test_snapshot_cannot_be_edited_or_deleted(self):
        document = self.prepare()
        document.snapshot = {"changed": True}
        with self.assertRaises(ValidationError):
            document.save()
        with self.assertRaises(ValidationError):
            document.delete()

    def test_discard_preserves_snapshot_and_records_reason_only_once(self):
        document = self.prepare()
        snapshot = document.snapshot
        args = dict(document_id=document.pk, actor=self.cashier, branch=self.branch, reason="Corregir receptor")
        cancel_draft(**args)
        cancel_draft(**args)
        document.refresh_from_db()
        self.assertEqual(document.snapshot, snapshot)
        self.assertEqual(document.cancel_reason, "Corregir receptor")
        self.assertEqual(document.events.filter(action="CANCELLED").count(), 1)
        with self.assertRaises(ValidationError):
            document.save()

    def test_discard_requires_reason_permission_and_branch(self):
        document = self.prepare()
        args = dict(document_id=document.pk, actor=self.cashier, branch=self.branch, reason="")
        with self.assertRaises(ValidationError):
            cancel_draft(**args)
        args["reason"] = "Corrección"
        args["actor"] = self.make_user("sin-permiso-descartar")
        with self.assertRaises(PermissionDenied):
            cancel_draft(**args)
        args["actor"] = self.cashier
        args["branch"] = Branch.objects.create(code="FOREIGN", name="Sede ajena")
        with self.assertRaises(ValidationError):
            cancel_draft(**args)

    def test_event_failure_rolls_back_document(self):
        with patch("apps.fiscal.services.FiscalEvent.objects.create", side_effect=RuntimeError("Audit failure")):
            with self.assertRaises(RuntimeError):
                self.prepare()
        self.assertFalse(FiscalDocument.objects.exists())

    def test_fake_fiscal_acceptance_is_rejected_by_database(self):
        document = self.prepare()
        with self.assertRaises(IntegrityError), transaction.atomic():
            FiscalDocument.objects.filter(pk=document.pk).update(status="ACCEPTED")

    def test_configuration_starts_pending_and_does_not_activate_emission(self):
        profile = FiscalProfile.objects.create(issuer=self.issuer)
        self.assertEqual(len(profile.pending_decisions), 5)
        document = self.prepare()
        self.assertTrue(document.snapshot["pending_decisions"])
        with self.assertRaisesMessage(ValidationError, "Emisión real no habilitada"):
            submit_document(document=document, actor=self.cashier)

    def test_confirmed_configuration_still_cannot_emit(self):
        FiscalProfile.objects.create(issuer=self.issuer, modality="CONTRIBUTOR", billing_trigger="PAYMENT",
                                     provider_name="Proveedor de prueba", document_types=["03"],
                                     tax_rules_confirmed=True, receiver_rules_confirmed=True,
                                     confirmation_reference="Prueba de configuración")
        document = self.prepare()
        with self.assertRaises(ValidationError):
            submit_document(document=document, actor=self.cashier)
        self.assertEqual(document.status, FiscalDocument.Status.DRAFT)

    def test_unknown_document_type_cannot_be_prepared(self):
        with self.assertRaises(ValidationError):
            self.prepare(document_type="99")

    def test_configuration_validates_confirmation_reference(self):
        profile = FiscalProfile(issuer=self.issuer, tax_rules_confirmed=True)
        with self.assertRaises(ValidationError):
            profile.full_clean()
        form = FiscalProfileForm(data={"modality": "PENDING", "billing_trigger": "PENDING", "document_types": ["99"]})
        self.assertFalse(form.is_valid())

    def test_configuration_changes_are_versioned_and_do_not_rewrite_drafts(self):
        profile = save_profile(actor=self.cashier, issuer_id=self.issuer.pk, values={"provider_name": "Primero"})
        document = self.prepare()
        save_profile(actor=self.cashier, issuer_id=self.issuer.pk, values={"provider_name": "Segundo"})
        self.assertEqual(profile.revisions.count(), 2)
        self.assertEqual(profile.revisions.order_by("pk").first().snapshot["provider_name"], "Primero")
        document.refresh_from_db()
        self.assertEqual(document.snapshot["profile"]["provider_name"], "Primero")

    def test_web_requires_permissions_before_resolving_customer(self):
        user = self.make_user("no-fiscal-web")
        self.open_session(user)
        self.assertEqual(self.client.get(reverse("fiscal:list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("fiscal:create", args=[999999])).status_code, 403)

    def test_web_create_and_detail_display_draft_warning(self):
        self.open_session()
        url = reverse("fiscal:create", args=[self.customer.pk])
        response = self.client.get(url)
        self.assertContains(response, "Guardar borrador para revisión")
        response = self.client.post(url, {"issuer": self.issuer.pk, "document_type": "03",
                                         "charges": [self.charge.pk], "proposed_issue_date": "2026-10-01",
                                         "request_key": str(uuid.uuid4())}, follow=True)
        self.assertContains(response, "BORRADOR SIN VALIDEZ TRIBUTARIA")
        self.assertContains(response, "Impuestos, descuentos fiscales y total fiscal: pendientes")
        self.assertContains(response, "Preparación de facturación")

    def test_web_list_searches_exact_customer_code_in_active_branch(self):
        self.prepare()
        self.open_session()
        response = self.client.get(reverse("fiscal:list"), {"customer_code": self.customer.code})
        self.assertContains(response, reverse("fiscal:create", args=[self.customer.pk]))
        self.assertEqual(len(response.context["documents"]), 1)

    def test_web_hides_other_branch_documents_and_customers(self):
        document = self.prepare()
        other = Branch.objects.create(code="BRANCH2", name="Segunda sede")
        self.open_session()
        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = other.pk
        session.save()
        self.assertEqual(self.client.get(reverse("fiscal:detail", args=[document.public_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("fiscal:create", args=[self.customer.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("fiscal:list")), str(document.public_id))
        self.assertEqual(self.client.post(reverse("fiscal:cancel", args=[document.public_id]), {"reason": "test"}).status_code, 404)

    def test_web_rejects_forged_foreign_charge(self):
        self.open_session()
        response = self.client.post(reverse("fiscal:create", args=[self.customer.pk]), {
            "issuer": self.issuer.pk, "document_type": "03", "charges": [999999],
            "proposed_issue_date": "2026-10-01", "request_key": str(uuid.uuid4()),
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FiscalDocument.objects.exists())

    def test_web_cancel_only_accepts_post(self):
        document = self.prepare()
        self.open_session()
        self.assertEqual(self.client.get(reverse("fiscal:cancel", args=[document.public_id])).status_code, 405)

    def test_web_profile_preserves_pending_values_and_records_revision(self):
        self.open_session()
        response = self.client.get(reverse("fiscal:profile", args=[self.issuer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FiscalProfile.objects.exists())  # GET no escribe.
        response = self.client.post(reverse("fiscal:profile", args=[self.issuer.pk]), {
            "modality": "PENDING", "billing_trigger": "PENDING", "provider_name": "Por evaluar",
        }, follow=True)
        self.assertContains(response, "La emisión real continúa bloqueada")
        self.assertEqual(FiscalProfile.objects.get().document_types, [])
        self.assertEqual(FiscalProfileRevision.objects.count(), 1)

    def test_admin_evidence_cannot_be_added_changed_or_deleted(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        request = RequestFactory().get("/admin/")
        request.user = self.cashier
        for model, admin_type in ((FiscalDocument, FiscalDocumentAdmin), (FiscalEvent, FiscalEventAdmin),
                                  (FiscalProfileRevision, FiscalProfileRevisionAdmin)):
            admin = admin_type(model, AdminSite())
            self.assertFalse(admin.has_add_permission(request))
            self.assertFalse(admin.has_change_permission(request))
            self.assertFalse(admin.has_delete_permission(request))
