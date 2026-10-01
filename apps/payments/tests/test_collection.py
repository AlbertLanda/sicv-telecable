"""Reglas actuales de ventanilla; históricos parciales conservan su significado."""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections, close_old_connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer
from apps.organization.models import Branch, Office
from apps.payments.collection import collect_payment
from apps.payments.models import Charge, Payment, PaymentOperationEvent, PaymentSubmission, Receipt, ReceiptSequence
from apps.payments.services import register_payment
from apps.payments.tests.base import PaymentsTestCase


class CollectionTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()
        self.actor = self.make_user("collector", permissions=["add_payment", "view_receipt", "confirm_payment", "void_payment"])
        self.day = timezone.localdate()
        self.charge = Charge.objects.create(customer=self.customer, concept=Charge.Concept.MONTHLY,
            description="Mensualidad de prueba", amount=80, due_date=self.day)
        self.sequence = ReceiptSequence.objects.create(code="TESTCOL", series="TESTCOL", label="Prueba", autonumber=True)

    def collect(self, **overrides):
        values = dict(request_key=uuid.uuid4(), expected_total=Decimal("80"), customer=self.customer,
            amount=Decimal("80"), method=Payment.Method.CASH, branch=self.branch, user=self.actor,
            series=self.sequence, selected_charge_ids=[self.charge.pk])
        values.update(overrides)
        return collect_payment(**values)

    def assert_empty(self):
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(Receipt.objects.count(), 0)
        self.assertEqual(PaymentSubmission.objects.count(), 0)
        self.sequence.refresh_from_db()
        self.assertEqual(self.sequence.last_number, 0)

    def test_complete_selected_month_leaves_other_month_unpaid(self):
        other = Charge.objects.create(customer=self.customer, concept="MONTHLY", amount=80, due_date=self.day)
        payment, receipt = self.collect()
        self.assertTrue(payment.full_monthly_only)
        self.assertEqual(self.charge.balance_on(), 0)
        self.assertEqual(other.balance_on(), 80)
        self.assertEqual(receipt.payment_id, payment.pk)

    def test_partial_month_rejected_without_spending_a_number(self):
        with self.assertRaises(ValidationError):
            self.collect(amount=Decimal("40"), allocations=[(self.charge, Decimal("40"))])
        self.assert_empty()

    def test_automatic_distribution_cannot_end_in_a_partial_month(self):
        Charge.objects.create(customer=self.customer, concept="MONTHLY", amount=80, due_date=self.day)
        with self.assertRaises(ValidationError):
            self.collect(amount=Decimal("120"), expected_total=Decimal("160"), selected_charge_ids=None)
        self.assert_empty()

    def test_discount_is_applied_and_snapshotted(self):
        self.charge.early_discount = 5
        self.charge.discount_deadline = self.day
        self.charge.save()
        payment, _ = self.collect(amount=Decimal("75"), expected_total=Decimal("75"))
        self.assertEqual(payment.allocations.get().discount, 5)
        self.assertEqual(self.charge.balance_on(), 0)

    def test_history_partial_stays_payable_at_remaining_balance(self):
        register_payment(customer=self.customer, amount=30, method="CASH", branch=self.branch, user=self.actor, series=self.sequence)
        payment, _ = self.collect(amount=Decimal("50"), expected_total=Decimal("50"))
        self.assertEqual(payment.allocations.get().amount, 50)
        self.assertEqual(self.charge.balance_on(), 0)

    def test_equipment_charge_can_retain_installment_behavior(self):
        self.charge.concept = Charge.Concept.OTHER
        self.charge.save()
        payment, _ = self.collect(amount=Decimal("30"), allocations=[(self.charge, Decimal("30"))])
        self.assertEqual(payment.allocations.get().amount, 30)
        self.assertEqual(self.charge.balance_on(), 50)

    def test_same_request_returns_same_receipt_once(self):
        key = uuid.uuid4()
        first, receipt = self.collect(request_key=key)
        second, repeated = self.collect(request_key=key)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(receipt.pk, repeated.pk)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(PaymentOperationEvent.objects.count(), 1)
        self.sequence.refresh_from_db()
        self.assertEqual(self.sequence.last_number, 1)

    def test_same_key_different_data_is_rejected(self):
        key = uuid.uuid4()
        self.collect(request_key=key)
        with self.assertRaises(ValidationError):
            self.collect(request_key=key, note="Cambio")
        self.assertEqual(Payment.objects.count(), 1)

    def test_replay_voided_request_does_not_recharge(self):
        key = uuid.uuid4()
        payment, _ = self.collect(request_key=key)
        payment.void(user=self.actor, reason="Prueba")
        repeated, _ = self.collect(request_key=key)
        self.assertEqual(repeated.status, Payment.Status.VOIDED)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(self.charge.balance_on(), 80)

    def test_new_request_from_stale_automatic_screen_does_not_become_credit(self):
        self.collect(selected_charge_ids=None)
        with self.assertRaises(ValidationError):
            self.collect(selected_charge_ids=None)
        self.assertEqual(Payment.objects.count(), 1)

    def test_price_reduction_requires_refresh(self):
        self.charge.amount = 60
        self.charge.save()
        with self.assertRaises(ValidationError):
            self.collect()
        self.assert_empty()

    def test_pending_does_not_reduce_debt_and_confirm_reduces_once(self):
        payment, _ = self.collect(settled=False)
        self.assertEqual(self.charge.balance_on(), 80)
        payment.confirm(actor=self.actor)
        self.assertEqual(self.charge.balance_on(), 0)
        with self.assertRaises(ValidationError):
            payment.confirm(actor=self.actor)
        self.assertEqual(payment.operation_events.filter(action="CONFIRMED", actor=self.actor).count(), 1)

    def test_pending_cannot_confirm_after_another_collection(self):
        payment, _ = self.collect(settled=False)
        self.collect()
        with self.assertRaises(ValidationError):
            payment.confirm(actor=self.actor)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.operation_events.filter(action="CONFIRMED").count(), 0)

    def test_expired_discount_blocks_pending_confirmation(self):
        self.charge.early_discount = 5
        self.charge.discount_deadline = self.day
        self.charge.save()
        payment, _ = self.collect(settled=False, amount=Decimal("75"), expected_total=Decimal("75"))
        with self.assertRaises(ValidationError):
            payment.confirm(paid_at=timezone.now() + timedelta(days=1), actor=self.actor)
        self.assertEqual(self.charge.balance_on(), 75)

    def test_cancelled_charge_blocks_confirmation(self):
        payment, _ = self.collect(settled=False)
        self.charge.status = Charge.Status.CANCELLED
        self.charge.save()
        with self.assertRaises(ValidationError):
            payment.confirm(actor=self.actor)

    def test_void_restores_balance_records_actor_and_requires_reason(self):
        payment, _ = self.collect()
        with self.assertRaises(ValidationError):
            payment.void(user=self.actor, reason=" ")
        payment.void(user=self.actor, reason="  Error de caja  ")
        self.assertEqual(self.charge.balance_on(), 80)
        self.assertEqual(payment.void_reason, "Error de caja")
        self.assertEqual(payment.operation_events.get(action="VOIDED").actor, self.actor)
        with self.assertRaises(ValidationError):
            payment.void(user=self.actor, reason="Otra vez")

    def test_duplicate_charge_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.collect(selected_charge_ids=[self.charge.pk, self.charge.pk])
        self.assert_empty()

    def test_foreign_customer_charge_is_rejected(self):
        other = Customer.objects.create(code="OTHER", branch=self.branch, document_number="00000000", first_name="Prueba")
        foreign = Charge.objects.create(customer=other, concept="MONTHLY", amount=80, due_date=self.day)
        with self.assertRaises(ValidationError):
            self.collect(selected_charge_ids=[foreign.pk])
        self.assert_empty()

    def test_cancelled_charge_cannot_be_collected(self):
        self.charge.status = Charge.Status.CANCELLED
        self.charge.save()
        with self.assertRaises(ValidationError):
            self.collect()
        self.assert_empty()

    def test_nonfinite_and_fractional_allocations_are_rejected(self):
        for value in ("NaN", "Infinity", "0.001"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.collect(allocations=[(self.charge, Decimal(value))])
        self.assert_empty()

    def test_collect_requires_permission(self):
        with self.assertRaises(PermissionDenied):
            self.collect(user=self.cashier)
        self.assert_empty()

    def test_office_required_when_branch_uses_offices(self):
        Office.objects.create(branch=self.branch, code="COL-OFF", name="Ventanilla")
        with self.assertRaises(ValidationError):
            self.collect()
        self.assert_empty()

    def test_cross_branch_collection_retains_collection_branch(self):
        branch = Branch.objects.create(code="COL02", name="Otra sede")
        payment, _ = self.collect(branch=branch)
        self.assertEqual(payment.branch, branch)
        self.assertEqual(payment.customer.branch, self.branch)

    def test_confirmation_route_enforces_permission(self):
        payment, receipt = self.collect(settled=False)
        self.login(self.cashier)
        url = reverse("payments:confirm", args=[payment.pk])
        self.assertEqual(self.client.post(url).status_code, 403)
        self.login(self.actor)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse("payments:receipt_detail", args=[receipt.pk]))
        self.assertEqual(self.charge.balance_on(), 0)

    def test_mutation_routes_reject_other_collection_branch(self):
        branch = Branch.objects.create(code="COL02", name="Otra sede")
        payment, _ = self.collect(branch=branch, settled=False)
        self.login(self.actor)
        for name, data in (("confirm", {}), ("void", {"reason": "Error"})):
            self.assertEqual(self.client.post(reverse("payments:" + name, args=[payment.pk]), data).status_code, 404)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)

    def test_web_repeated_post_returns_original_receipt(self):
        self.login(self.actor)
        self.sequence.is_active = True
        self.sequence.save()
        url = reverse("payments:register", args=[self.customer.pk]) + f"?charges={self.charge.pk}"
        response = self.client.get(url)
        form = response.context["form"]
        data = {"amount": "80.00", "expected_total": str(form["expected_total"].value()),
                "request_key": str(form["request_key"].value()), "method": "CASH", "series": self.sequence.code,
                "charges": [self.charge.pk]}
        first = self.client.post(url, data)
        second = self.client.post(url, data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first["Location"], second["Location"])
        self.assertEqual(Payment.objects.count(), 1)

    def test_web_partial_or_nonfinite_allocation_cannot_create_payment(self):
        self.login(self.actor)
        self.sequence.is_active = True
        self.sequence.save()
        url = reverse("payments:register", args=[self.customer.pk])
        for value in ("40.00", "NaN", "Infinity", "0.001"):
            data = {"amount": "80.00", "expected_total": "80.00", "request_key": str(uuid.uuid4()),
                    "method": "CASH", "series": self.sequence.code, f"charge_{self.charge.pk}": value}
            with self.subTest(value=value):
                self.assertEqual(self.client.post(url, data).status_code, 200)
                self.assert_empty()

    def test_atc_cannot_collect_or_mutate_an_unauthorized_office(self):
        atc = self.make_user("atc-limited", role="ATC", permissions=["add_payment", "confirm_payment", "void_payment", "view_receipt"])
        office = Office.objects.create(branch=self.branch, code="LOCKED", name="Caja ajena")
        with self.assertRaises(PermissionDenied):
            self.collect(user=atc, office=office)
        payment, _ = self.collect(office=office, settled=False)
        self.login(atc)
        for name in ("confirm", "void"):
            self.assertEqual(self.client.post(reverse("payments:" + name, args=[payment.pk]), {"reason": "Prueba"}).status_code, 404)

    def test_financial_admin_cannot_bypass_service(self):
        for model in (Payment, Receipt, PaymentSubmission, PaymentOperationEvent):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(None))
            self.assertFalse(model_admin.has_change_permission(None))
            self.assertFalse(model_admin.has_delete_permission(None))


@skipUnless(connection.vendor == "postgresql", "Requiere bloqueo real de filas en PostgreSQL; se ejecuta en CI.")
class ConcurrentCollectionTests(TransactionTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="CONCUR", name="Sede de prueba")
        self.customer = Customer.objects.create(code="CONCUR", branch=self.branch, first_name="Prueba", document_number="00000001")
        self.actor = get_user_model().objects.create_superuser(username="concur", password="test", branch=self.branch)
        self.charge = Charge.objects.create(customer=self.customer, concept="MONTHLY", amount=80, due_date=timezone.localdate())
        self.sequence = ReceiptSequence.objects.create(code="CONCUR", series="CONCUR", label="Prueba", autonumber=True)

    def collect(self, key):
        return collect_payment(request_key=key, expected_total=Decimal("80"),
            customer=Customer.objects.get(pk=self.customer.pk), amount=Decimal("80"), method="CASH",
            branch=Branch.objects.get(pk=self.branch.pk), user=get_user_model().objects.get(pk=self.actor.pk),
            series=ReceiptSequence.objects.get(pk=self.sequence.pk), selected_charge_ids=[self.charge.pk])

    def race(self, *actions):
        barrier = Barrier(len(actions))
        def run(action):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                barrier.wait(timeout=5)
                try:
                    action()
                    return "ok"
                except ValidationError:
                    return "rejected"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            futures = [pool.submit(run, action) for action in actions]
            return [future.result(timeout=20) for future in futures]

    def test_same_request_from_two_connections_returns_one_receipt(self):
        key = uuid.uuid4()
        self.assertEqual(self.race(lambda: self.collect(key), lambda: self.collect(key)), ["ok", "ok"])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Receipt.objects.count(), 1)
        self.assertEqual(PaymentOperationEvent.objects.count(), 1)
        self.sequence.refresh_from_db()
        self.assertEqual(self.sequence.last_number, 1)

    def test_different_requests_cannot_collect_same_debt_twice(self):
        result = self.race(lambda: self.collect(uuid.uuid4()), lambda: self.collect(uuid.uuid4()))
        self.assertCountEqual(result, ["ok", "rejected"])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(self.charge.balance_on(), 0)

    def test_confirmation_and_new_collection_cannot_overapply(self):
        payment, _ = collect_payment(request_key=uuid.uuid4(), expected_total=Decimal("80"),
            customer=self.customer, amount=80, method="CASH", branch=self.branch, user=self.actor,
            series=self.sequence, selected_charge_ids=[self.charge.pk], settled=False)
        result = self.race(lambda: Payment.objects.get(pk=payment.pk).confirm(actor=self.actor), lambda: self.collect(uuid.uuid4()))
        self.assertCountEqual(result, ["ok", "rejected"])
        self.assertEqual(Payment.objects.filter(status=Payment.Status.REGISTERED).count(), 1)
        self.assertEqual(self.charge.balance_on(), 0)

    def test_two_voids_restore_balance_only_once(self):
        payment, _ = self.collect(uuid.uuid4())
        def void():
            Payment.objects.get(pk=payment.pk).void(user=self.actor, reason="Error")
        self.assertCountEqual(self.race(void, void), ["ok", "rejected"])
        self.assertEqual(self.charge.balance_on(), 80)
        self.assertEqual(PaymentOperationEvent.objects.filter(action="VOIDED").count(), 1)
