"""
Emisión de la mensualidad: a quién se le cobra, cuánto y cuándo vence.

Lo que se fija aquí es que el ciclo se pueda volver a correr sin duplicar
deuda. Es la única garantía que permite relanzarlo cuando se corta a la mitad,
y sin ella la reacción natural -"lo corro otra vez"- le cobraría dos veces el
mes al abonado.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.payments.models import Charge
from apps.payments.services import generate_monthly_charges
from apps.payments.tests.base import PaymentsTestCase
from apps.services.models import BillingPolicy, Subscription


PERIOD = date(2026, 9, 1)


class MonthlyChargeGenerationTests(PaymentsTestCase):
    def test_an_active_subscription_is_charged_its_monthly_price(self):
        result = generate_monthly_charges(PERIOD)

        self.assertEqual(len(result["created"]), 1)

        charge = result["created"][0]

        self.assertEqual(charge.customer, self.customer)
        self.assertEqual(charge.subscription, self.subscription)
        self.assertEqual(charge.concept, Charge.Concept.MONTHLY)
        self.assertEqual(charge.period, PERIOD)
        self.assertEqual(charge.amount, self.subscription.total_monthly_price)

    def test_by_calendar_month_it_expires_when_the_month_closes(self):
        charge = generate_monthly_charges(PERIOD)["created"][0]

        self.assertEqual(charge.due_date, date(2026, 9, 30))

    def test_the_early_payment_discount_travels_with_its_deadline(self):
        charge = generate_monthly_charges(PERIOD)["created"][0]

        self.assertEqual(charge.early_discount, Decimal("5.00"))
        self.assertEqual(charge.discount_deadline, date(2026, 9, 10))

    def test_the_cut_date_comes_from_the_policy(self):
        charge = generate_monthly_charges(PERIOD)["created"][0]

        self.assertEqual(charge.cut_date, date(2026, 10, 15))

    def test_by_anniversary_it_expires_on_the_installation_day(self):
        """El abonado paga el día que se le instaló, no a fin de mes.

        Es la fecha que tiene interiorizada: moverla al cierre del mes le
        cambiaría el compromiso sin habérselo dicho.
        """
        self.policy.billing_mode = BillingPolicy.Mode.ANNIVERSARY
        self.policy.discount_days_before_due = 3
        self.policy.cut_days_after_due = 10
        self.policy.save()

        charge = generate_monthly_charges(PERIOD)["created"][0]

        self.assertEqual(charge.due_date, date(2026, 9, 15))
        self.assertEqual(charge.discount_deadline, date(2026, 9, 12))
        self.assertEqual(charge.cut_date, date(2026, 9, 25))

    def test_running_it_twice_does_not_duplicate_the_debt(self):
        generate_monthly_charges(PERIOD)
        second = generate_monthly_charges(PERIOD)

        self.assertEqual(second["created"], [])
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(Charge.objects.filter(period=PERIOD).count(), 1)

    def test_a_subscription_that_is_not_active_is_not_charged(self):
        self.subscription.status = Subscription.Status.CUT
        self.subscription.save()

        result = generate_monthly_charges(PERIOD)

        self.assertEqual(result["created"], [])

    def test_a_subscription_without_a_policy_is_not_charged(self):
        """Sin política no se sabe cuándo vence ni cuándo se corta.

        Emitir igual obligaría a inventar un vencimiento, y ese cargo
        decidiría por su cuenta la fecha de corte del abonado.
        """
        self.subscription.billing_policy = None
        self.subscription.save()

        result = generate_monthly_charges(PERIOD)

        self.assertEqual(result["created"], [])
        self.assertEqual(result["skipped"], 0)

    def test_a_month_before_the_installation_is_not_charged(self):
        self.subscription.installation_date = date(2026, 12, 1)
        self.subscription.save()

        result = generate_monthly_charges(PERIOD)

        self.assertEqual(result["created"], [])

    def test_a_dry_run_reports_without_saving(self):
        result = generate_monthly_charges(PERIOD, dry_run=True)

        self.assertEqual(len(result["created"]), 1)
        self.assertFalse(Charge.objects.exists())


class MonthlyChargeCommandTests(PaymentsTestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command("generar_cargos_mensuales", *args, stdout=out)

        return out.getvalue()

    def test_it_charges_the_requested_period(self):
        self.run_command("--periodo", "2026-09")

        charge = Charge.objects.get()

        self.assertEqual(charge.period, PERIOD)

    def test_a_dry_run_saves_nothing(self):
        output = self.run_command("--periodo", "2026-09", "--dry-run")

        self.assertIn("DRY RUN", output)
        self.assertFalse(Charge.objects.exists())

    def test_an_invalid_period_is_reported_without_a_traceback(self):
        with self.assertRaises(CommandError) as error:
            self.run_command("--periodo", "septiembre")

        self.assertIn("AAAA-MM", str(error.exception))

    def test_an_unknown_branch_is_reported(self):
        with self.assertRaises(CommandError) as error:
            self.run_command("--periodo", "2026-09", "--sede", "NOEXISTE")

        self.assertIn("NOEXISTE", str(error.exception))
