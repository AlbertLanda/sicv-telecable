from datetime import date
from decimal import Decimal

from apps.payments.models import Charge, Payment
from apps.payments.services import generate_monthly_charges, register_payment
from apps.payments.tests.base import PaymentsTestCase
from apps.services.models import BillingPolicy


class ConfirmedBillingRulesTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()
        self.policy = BillingPolicy.objects.get(code="ANNIVERSARY_PP10")
        self.subscription.billing_policy = self.policy
        self.subscription.base_monthly_fee = Decimal("89.00")
        self.subscription.installation_date = date(2026, 9, 14)
        self.subscription.billing_cycle = 14
        self.subscription.save()

    def charge(self, month=date(2026, 9, 1)):
        return generate_monthly_charges(month)["created"][0]

    def test_cycle_matches_confirmed_dates_and_discount_boundaries(self):
        charge = self.charge()
        self.assertEqual(self.policy.discount_days_before_due, 3)
        self.assertEqual(charge.period_label, "14/09/2026 - 13/10/2026")
        self.assertEqual(charge.due_date, date(2026, 10, 13))
        self.assertEqual(charge.discount_deadline, date(2026, 10, 10))
        self.assertEqual(charge.cut_date, date(2026, 10, 14))
        self.assertEqual(charge.amount_due_on(date(2026, 10, 10)), Decimal("79.00"))
        self.assertEqual(charge.amount_due_on(date(2026, 10, 11)), Decimal("89.00"))
        self.assertEqual(charge.amount_due_on(date(2026, 10, 13)), Decimal("89.00"))

    def test_installation_day_is_anchor_if_no_legacy_cycle(self):
        self.subscription.billing_cycle = None
        self.subscription.installation_date = date(2026, 10, 7)
        self.subscription.save()
        charge = self.charge(date(2026, 10, 1))
        self.assertEqual(charge.period_label, "07/10/2026 - 06/11/2026")
        self.assertEqual(charge.due_date, date(2026, 11, 6))

    def test_legacy_cycle_survives_plan_with_old_installation_date(self):
        self.subscription.installation_date = date(2021, 4, 3)
        self.subscription.save()
        self.assertEqual(self.charge().period_start, date(2026, 9, 14))

    def test_short_month_clips_anchor_without_period_gaps(self):
        self.subscription.billing_cycle = 31
        self.subscription.installation_date = date(2026, 1, 31)
        self.subscription.save()
        jan = self.charge(date(2026, 1, 1))
        feb = self.charge(date(2026, 2, 1))
        self.assertEqual((jan.period_start, jan.period_end), (date(2026, 1, 31), date(2026, 2, 27)))
        self.assertEqual((feb.period_start, feb.period_end), (date(2026, 2, 28), date(2026, 3, 30)))

    def test_first_calendar_month_is_prorated_and_next_is_full(self):
        self.subscription.billing_policy = BillingPolicy.objects.get(code="CALENDAR_PP5")
        self.subscription.installation_date = date(2026, 10, 7)
        self.subscription.save()
        first = self.charge(date(2026, 10, 1))
        self.assertEqual(first.period_label, "07/10/2026 - 31/10/2026")
        self.assertEqual(first.amount, Decimal("74.25"))  # S/2,97 × 25 días; mes comercial de 30 días.
        self.assertEqual(first.discount_deadline, date(2026, 10, 29))
        self.assertEqual(first.due_date, date(2026, 10, 31))
        self.assertEqual(self.charge(date(2026, 11, 1)).amount, Decimal("89.00"))
        self.assertEqual(generate_monthly_charges(date(2026, 10, 1))["created"], [])

    def test_calendar_discount_clips_to_last_february_day(self):
        self.subscription.billing_policy = BillingPolicy.objects.get(code="CALENDAR_PP5")
        self.subscription.installation_date = date(2025, 1, 7)
        self.subscription.save()
        feb = self.charge(date(2026, 2, 1))
        leap = self.charge(date(2028, 2, 1))
        self.assertEqual(feb.discount_deadline, date(2026, 2, 28))
        self.assertEqual(leap.discount_deadline, date(2028, 2, 29))
        self.assertEqual(feb.amount_due_on(date(2026, 2, 28)), Decimal("84.00"))
        self.assertEqual(feb.amount_due_on(date(2026, 3, 1)), Decimal("89.00"))

    def test_paid_discount_does_not_turn_into_debt_after_deadline(self):
        charge = self.charge()
        payment, _ = register_payment(
            customer=self.customer, amount=Decimal("79.00"), method=Payment.Method.CASH,
            user=self.cashier, branch=self.branch, allocations=[(charge, Decimal("79.00"))],
            day=date(2026, 10, 10), full_monthly_only=True,
        )
        self.assertEqual(payment.allocations.get().discount, Decimal("10.00"))
        self.assertEqual(charge.paid_amount, Decimal("79.00"))
        self.assertEqual(charge.balance_on(date(2026, 10, 14)), 0)
        self.assertEqual(charge.refresh_status(day=date(2026, 10, 14)), Charge.Status.PAID)
        payment.void(self.cashier, "Anulación de prueba")
        self.assertEqual(charge.balance_on(date(2026, 10, 14)), Decimal("89.00"))
