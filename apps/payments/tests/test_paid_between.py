"""El día de cobro de un pago: la regla que usa la caja del día."""

from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

from apps.payments.models import Payment
from apps.payments.services import paid_between
from apps.payments.tests.base import PaymentsTestCase


def moment(day):
    return timezone.make_aware(datetime(2026, 9, day, 10, 0))


class PaidBetweenTests(PaymentsTestCase):
    def pay(self, *, received, paid=None, status=Payment.Status.REGISTERED):
        return Payment.objects.create(
            customer=self.customer,
            amount=Decimal("10.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            received_by=self.cashier,
            received_at=moment(received),
            paid_at=moment(paid) if paid else None,
            status=status,
        )

    def found(self, date_from, date_to):
        return set(
            Payment.objects.filter(paid_between(date_from, date_to))
            .values_list("pk", flat=True)
        )

    def test_the_day_is_the_real_payment_date(self):
        paid_later = self.pay(received=5, paid=12)
        self.pay(received=12, paid=20)

        self.assertEqual(
            self.found(date(2026, 9, 12), date(2026, 9, 12)), {paid_later.pk}
        )

    def test_a_pending_payment_counts_on_its_registration_day(self):
        pending = self.pay(received=12, status=Payment.Status.PENDING)

        self.assertEqual(
            self.found(date(2026, 9, 12), date(2026, 9, 12)), {pending.pk}
        )

    def test_both_ends_of_the_range_are_included(self):
        first = self.pay(received=10, paid=10)
        last = self.pay(received=12, paid=12)
        self.pay(received=13, paid=13)

        self.assertEqual(
            self.found(date(2026, 9, 10), date(2026, 9, 12)), {first.pk, last.pk}
        )
