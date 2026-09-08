"""
El comando que siembra cobranza de prueba sobre un abonado real.

Lo que se fija aquí es que se pueda volver a correr sin inflar la deuda. Es la
reacción natural cuando la pantalla no muestra lo esperado -«lo corro otra
vez»- y si duplicara mensualidades dejaría la base de pruebas mintiendo.
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.payments.models import Charge, Payment, PaymentCommitment
from apps.payments.tests.base import PaymentsTestCase
from apps.services.models import Subscription


class TestDataCommandTests(PaymentsTestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command(
            "generar_datos_cobranza_prueba",
            "--abonado",
            self.customer.code,
            *args,
            stdout=out,
        )

        return out.getvalue()

    def setUp(self):
        super().setUp()

        # El abonado base nace como una suscripción recién registrada: en
        # instalación y con mensualidad en cero, que es lo que el comando
        # tiene que dejar facturable.
        self.subscription.status = Subscription.Status.INSTALLATION
        self.subscription.installation_date = None
        self.subscription.base_monthly_fee = 0
        self.subscription.save()

    def test_it_makes_the_subscription_billable(self):
        """Sin esto el ciclo no emite nada y la pantalla se vería vacía.

        Una suscripción en instalación, sin fecha y con tarifa en cero no
        genera mensualidades, y la deuda vacía no explicaría por qué.
        """
        self.run_command()

        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.status, Subscription.Status.ACTIVE)
        self.assertIsNotNone(self.subscription.installation_date)
        self.assertEqual(
            self.subscription.base_monthly_fee, self.plan.monthly_price
        )

    def test_it_issues_the_requested_months(self):
        self.run_command("--meses", "3")

        monthly = Charge.objects.filter(concept=Charge.Concept.MONTHLY)

        self.assertEqual(monthly.count(), 3)

    def test_it_issues_a_charge_the_cycle_does_not_generate(self):
        """La lista no debe ser uniforme: se ve mejor con un cargo suelto."""
        self.run_command()

        self.assertTrue(
            Charge.objects.filter(
                concept=Charge.Concept.REACTIVATION
            ).exists()
        )

    def test_it_registers_payments_with_their_receipts(self):
        self.run_command()

        self.assertEqual(Payment.objects.count(), 2)
        self.assertTrue(
            all(hasattr(payment, "receipt") for payment in Payment.objects.all())
        )

    def test_it_leaves_debt_still_open(self):
        """La pantalla de deudas tiene que tener algo que mostrar."""
        self.run_command()

        self.assertTrue(Charge.objects.filter(customer=self.customer).outstanding())

    def test_it_grants_one_active_commitment(self):
        self.run_command()

        commitment = PaymentCommitment.objects.get()

        self.assertEqual(commitment.status, PaymentCommitment.Status.ACTIVE)
        self.assertTrue(commitment.charges.exists())

    def test_running_it_twice_does_not_duplicate_anything(self):
        self.run_command("--meses", "3")

        charges = Charge.objects.count()
        payments = Payment.objects.count()
        commitments = PaymentCommitment.objects.count()

        self.run_command("--meses", "3")

        self.assertEqual(Charge.objects.count(), charges)
        self.assertEqual(Payment.objects.count(), payments)
        self.assertEqual(PaymentCommitment.objects.count(), commitments)

    def test_a_dry_run_saves_nothing(self):
        output = self.run_command("--dry-run")

        self.assertIn("DRY RUN", output)
        self.assertFalse(Charge.objects.exists())
        self.assertFalse(Payment.objects.exists())

    def test_an_unknown_customer_is_reported_without_a_traceback(self):
        out = StringIO()

        with self.assertRaises(CommandError) as error:
            call_command(
                "generar_datos_cobranza_prueba",
                "--abonado",
                "NO-EXISTE",
                stdout=out,
            )

        self.assertIn("NO-EXISTE", str(error.exception))

    def test_zero_months_is_rejected(self):
        with self.assertRaises(CommandError):
            self.run_command("--meses", "0")

    def test_a_customer_without_a_billing_policy_is_reported(self):
        """Sin política de cobro no se puede facturar, y hay que decirlo.

        Inventar una aquí le pondría al abonado un vencimiento y una fecha de
        corte que nadie acordó con él.
        """
        self.subscription.billing_policy = None
        self.subscription.save()

        with self.assertRaises(CommandError) as error:
            self.run_command()

        self.assertIn("política de cobro", str(error.exception))
