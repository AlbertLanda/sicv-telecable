from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.organization.models import Branch
from apps.payments.adjustments import request_adjustment, review_adjustment, scoped_charges
from apps.payments.balances import with_charge_balances
from apps.payments.models import Charge, DebtAdjustment, Payment
from apps.payments.services import register_payment
from apps.payments.tests.base import PaymentsTestCase


class DebtAdjustmentTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()
        self.actor = self.make_user("adjust-requester", role="ATC")
        self.reviewer = self.make_user("adjust-reviewer", role="ACCOUNTING")
        self.charge = Charge.objects.create(customer=self.customer, subscription=self.subscription,
            concept="MONTHLY", period=timezone.localdate().replace(day=1), amount=80, due_date=timezone.localdate())

    def request(self, **overrides):
        values = dict(charge_id=self.charge.pk, actor=self.actor, amount=20, reason="Corrección comercial de prueba", reference="Sustento TEST-1", request_key=uuid.uuid4())
        values.update(overrides)
        return request_adjustment(**values)

    def approve(self, adjustment, **overrides):
        values = dict(adjustment_id=adjustment.pk, actor=self.reviewer, decision="APPROVED", note="Sustento revisado")
        values.update(overrides)
        return review_adjustment(**values)

    def payment(self, amount, **overrides):
        values = dict(customer=self.customer, amount=amount, method="CASH", branch=self.branch, user=self.actor)
        values.update(overrides)
        return register_payment(**values)[0]

    def test_request_does_not_change_debt_approval_keeps_original_and_sql_matches(self):
        adjustment = self.request()
        self.assertEqual(self.charge.balance_on(), 80)
        self.approve(adjustment)
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.amount, 80)
        self.assertEqual(self.charge.balance_on(), 60)
        annotated = with_charge_balances(Charge.objects.filter(pk=self.charge.pk), timezone.localdate()).get()
        self.assertEqual(annotated.dashboard_balance, Decimal("60"))
        adjustment.refresh_from_db()
        self.assertEqual(Decimal(adjustment.result_snapshot["before"]["balance"]), 80)
        self.assertEqual(Decimal(adjustment.result_snapshot["after"]["balance"]), 60)
        self.assertFalse(Payment.objects.exists())

    def test_full_duplicate_credit_stays_zero_after_discount_expiry_without_fake_payment(self):
        self.charge.early_discount, self.charge.discount_deadline = 5, timezone.localdate()
        self.charge.save()
        self.approve(self.request(amount=80))
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, "ADJUSTED")
        self.assertEqual(self.charge.balance_on(timezone.localdate() + timedelta(days=10)), 0)
        self.assertFalse(Payment.objects.exists())

    def test_partial_credit_preserves_earned_discount_when_remaining_balance_is_paid(self):
        self.charge.early_discount, self.charge.discount_deadline = 5, timezone.localdate()
        self.charge.save()
        self.approve(self.request(amount=20))
        self.assertEqual(self.charge.balance_on(), 55)
        payment = self.payment(55)
        self.assertEqual(payment.allocations.get().discount, 5)
        self.assertEqual(self.charge.balance_on(timezone.localdate() + timedelta(days=10)), 0)
        self.assertEqual(self.charge.nominal_balance, 0)

    def test_temporary_zero_balance_does_not_hide_remainder_after_discount_deadline(self):
        self.charge.early_discount, self.charge.discount_deadline = 5, timezone.localdate()
        self.charge.save()
        self.payment(10)
        self.approve(self.request(amount=65))
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, "PARTIALLY_PAID")
        self.assertEqual(self.charge.balance_on(), 0)
        self.assertEqual(self.charge.balance_on(timezone.localdate() + timedelta(days=1)), 5)

    def test_reversal_with_earned_early_discount_does_not_grant_discount_twice(self):
        self.charge.early_discount, self.charge.discount_deadline = 5, timezone.localdate()
        self.charge.save()
        original = self.request()
        self.approve(original)
        self.payment(55)
        self.approve(self.request(reversal_id=original.pk))
        self.assertEqual(self.charge.balance_on(), 20)
        annotated = with_charge_balances(Charge.objects.filter(pk=self.charge.pk), timezone.localdate()).get()
        self.assertEqual(annotated.dashboard_balance, 20)
        payment = self.payment(20)
        self.assertEqual(payment.allocations.get().discount, 0)
        self.assertEqual(self.charge.balance_on(timezone.localdate() + timedelta(days=5)), 0)

    def test_cannot_reduce_paid_money_or_cancelled_charge(self):
        self.payment(60)
        with self.assertRaises(ValidationError):
            self.request(amount=21)
        self.charge.status = "CANCELLED"
        self.charge.save()
        with self.assertRaises(ValidationError):
            self.request(amount=10)

    def test_double_request_replay_pending_limit_and_conflicting_key(self):
        key = uuid.uuid4()
        adjustment = self.request(request_key=key)
        self.assertEqual(self.request(request_key=key).pk, adjustment.pk)
        for values in [dict(request_key=key, amount=30), dict(amount=10)]:
            with self.assertRaises(ValidationError):
                self.request(**values)
        self.assertEqual(DebtAdjustment.objects.count(), 1)

    def test_changed_debt_requires_rejection_and_new_request(self):
        adjustment = self.request()
        self.payment(10)
        with self.assertRaises(ValidationError):
            self.approve(adjustment)
        self.approve(adjustment, decision="REJECTED", note="Hubo un cobro posterior")
        self.approve(self.request(amount=20))
        self.assertEqual(self.charge.balance_on(), 50)

    def test_pending_collection_cannot_confirm_stale_amount_after_approval(self):
        payment = self.payment(80, settled=False)
        self.approve(self.request())
        with self.assertRaises(ValidationError):
            payment.confirm(actor=self.actor)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "PENDING")

    def test_self_approval_forbidden_even_admin_and_foreign_branch_forbidden(self):
        adjustment = self.request()
        self.actor.is_superuser = True
        self.actor.save()
        with self.assertRaises(PermissionDenied):
            self.approve(adjustment, actor=self.actor)
        self.reviewer.branch = Branch.objects.create(code="OTHER-ADJ", name="Otra sede")
        self.reviewer.save()
        self.assertFalse(scoped_charges(self.reviewer).filter(pk=self.charge.pk).exists())
        with self.assertRaises(PermissionDenied):
            self.approve(adjustment)

    def test_reversal_is_complete_once_and_requires_independent_approval(self):
        original = self.request()
        self.approve(original)
        with self.assertRaises(ValidationError):
            self.request(amount=10, reversal_id=original.pk)
        undo = self.request(amount=20, reversal_id=original.pk)
        self.assertEqual(self.charge.balance_on(), 60)
        self.approve(undo)
        self.assertEqual(self.charge.balance_on(), 80)
        with self.assertRaises(ValidationError):
            self.request(amount=20, reversal_id=original.pk)
        original.refresh_from_db()
        self.assertEqual(original.status, "APPROVED")
        self.assertEqual(original.amount, 20)

    def test_reversal_after_remaining_debt_paid_restores_only_adjusted_amount(self):
        original = self.request()
        self.approve(original)
        self.payment(60)
        self.approve(self.request(reversal_id=original.pk))
        self.assertEqual(self.charge.balance_on(), 20)
        self.assertEqual(self.charge.paid_amount, 60)

    def test_rejection_and_invalid_amounts_leave_balance_untouched(self):
        for amount in [0, -1, "NaN", "1.001", "Infinity"]:
            with self.assertRaises(ValidationError):
                self.request(amount=amount)
        adjustment = self.request()
        self.approve(adjustment, decision="REJECTED")
        self.assertEqual(self.charge.balance_on(), 80)
        with self.assertRaises(ValidationError):
            self.approve(adjustment)

    def test_web_request_review_history_and_customer_entry(self):
        self.client.force_login(self.actor)
        self.assertContains(self.client.get(reverse("payments:adjustments"), {"q": self.customer.code}), "Ajustes de deuda")
        url = reverse("payments:adjustment_charge", args=[self.charge.pk])
        response = self.client.post(url, {"action": "request", "amount": "20", "reason": "Duplicado", "reference": "QA-TEST", "request_key": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 302)
        adjustment = DebtAdjustment.objects.get()
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(url), "Revisar solicitud")
        response = self.client.post(url, {"action": "review", "adjustment_id": adjustment.pk, "decision": "APPROVED", "note": "Validado"})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(url), "Historial conservado")
        self.assertEqual(self.charge.balance_on(), 60)

    def test_technical_role_cannot_open_or_post_adjustments(self):
        user = self.make_user("no-adjust", role="TECHNICIAN")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("payments:adjustments")).status_code, 403)
        with self.assertRaises(PermissionDenied):
            self.request(actor=user)
