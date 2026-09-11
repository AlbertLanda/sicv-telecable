"""
Compromiso de pago: aplaza el corte sin mover el saldo.

Lo que se fija aquí es que el compromiso **no** cancele deuda. Es la
confusión que haría perder dinero: si conceder un compromiso descontara el
saldo, el abonado quedaría al día sin haber pagado nada.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.payments.models import Charge, PaymentCommitment
from apps.payments.services import (
    grant_commitment,
    register_payment,
)
from apps.payments.tests.base import PaymentsTestCase


class CommitmentTestCase(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()

        self.overdue = self.make_charge(
            description="Mensualidad vencida",
            due_date=self.today - timedelta(days=20),
        )
        self.next_one = self.make_charge(
            description="Mensualidad del mes",
            due_date=self.today + timedelta(days=10),
        )

    def make_charge(self, **overrides):
        data = {
            "customer": self.customer,
            "subscription": None,
            "concept": Charge.Concept.OTHER,
            "amount": Decimal("80.00"),
        }
        data.update(overrides)

        return Charge.objects.create(**data)

    def grant(self, charges=None, **kwargs):
        kwargs.setdefault("committed_date", self.today + timedelta(days=7))
        kwargs.setdefault("reason", "El abonado cobra el viernes.")

        return grant_commitment(
            customer=self.customer,
            charges=charges if charges is not None else [self.overdue],
            user=self.cashier,
            **kwargs,
        )


class CommitmentGrantTests(CommitmentTestCase):
    def test_it_does_not_cancel_the_debt(self):
        """Comprometerse no es pagar.

        La deuda sigue siendo la misma: lo único que cambia es que el cargo
        deja de empujar al corte.
        """
        self.grant()

        self.overdue.refresh_from_db()

        self.assertEqual(self.overdue.status, Charge.Status.PENDING)
        self.assertEqual(self.overdue.balance, Decimal("80.00"))

    def test_the_committed_charge_is_protected_from_the_cut(self):
        self.grant()

        self.overdue.refresh_from_db()

        self.assertTrue(self.overdue.is_protected_from_cut())
        self.assertFalse(self.next_one.is_protected_from_cut())

    def test_without_an_explicit_amount_it_commits_the_full_balance(self):
        commitment = self.grant(charges=[self.overdue, self.next_one])

        self.assertEqual(commitment.amount, Decimal("160.00"))

    def test_the_abonado_can_commit_to_less_than_the_balance(self):
        """Se compromete por lo que puede, no por lo que debe.

        Registrar solo el total forzaría a inventar un acuerdo distinto del
        que realmente se hizo en ventanilla.
        """
        commitment = self.grant(amount=Decimal("50.00"))

        self.assertEqual(commitment.amount, Decimal("50.00"))

    def test_committing_more_than_the_balance_is_rejected(self):
        with self.assertRaises(ValidationError) as error:
            self.grant(amount=Decimal("500.00"))

        self.assertIn("supera el saldo", str(error.exception))

    def test_a_past_date_is_rejected(self):
        """Un plazo ya vencido no aplaza ningún corte."""
        with self.assertRaises(ValidationError) as error:
            self.grant(committed_date=self.today - timedelta(days=1))

        self.assertIn("futura", str(error.exception))

    def test_without_charges_it_is_rejected(self):
        """El compromiso protege cargos concretos, no la deuda futura.

        Dejarlo abierto le daría protección sobre meses que todavía no
        existían cuando se comprometió.
        """
        with self.assertRaises(ValidationError) as error:
            self.grant(charges=[])

        self.assertIn("al menos un cargo", str(error.exception))

    def test_a_reason_is_required(self):
        with self.assertRaises(ValidationError):
            self.grant(reason="   ")

    def test_a_paid_charge_cannot_be_committed(self):
        register_payment(
            customer=self.customer,
            amount=Decimal("80.00"),
            method="CASH",
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.overdue, Decimal("80.00"))],
        )
        self.overdue.refresh_from_db()

        with self.assertRaises(ValidationError) as error:
            self.grant()

        self.assertIn("saldo pendiente", str(error.exception))

    def test_a_charge_of_another_customer_is_rejected(self):
        from apps.customers.models import Customer

        other = Customer.objects.create(
            code="CLI002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="10101010",
            first_name="Ana",
            paternal_surname="Lopez",
        )
        foreign = Charge.objects.create(
            customer=other,
            concept=Charge.Concept.OTHER,
            description="Cargo ajeno",
            amount=Decimal("50.00"),
            due_date=self.today,
        )

        with self.assertRaises(ValidationError):
            self.grant(charges=[foreign])


class CommitmentLifecycleTests(CommitmentTestCase):
    def test_paying_the_charges_fulfills_it(self):
        commitment = self.grant()

        register_payment(
            customer=self.customer,
            amount=Decimal("80.00"),
            method="CASH",
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.overdue, Decimal("80.00"))],
        )

        self.assertEqual(commitment.evaluate(), PaymentCommitment.Status.FULFILLED)

    def test_the_date_passing_with_a_balance_breaks_it(self):
        """Se rompe por el paso del tiempo, no por una acción de nadie.

        Por eso se reevalúa al leerlo: sin esto, uno vencido seguiría
        figurando como vigente hasta que alguien lo tocara.
        """
        commitment = self.grant(committed_date=self.today + timedelta(days=1))

        later = self.today + timedelta(days=5)

        self.assertEqual(
            commitment.evaluate(day=later), PaymentCommitment.Status.BROKEN
        )

    def test_it_stays_active_while_the_date_has_not_arrived(self):
        commitment = self.grant()

        self.assertEqual(commitment.evaluate(), PaymentCommitment.Status.ACTIVE)

    def test_an_expired_commitment_stops_protecting_the_charge(self):
        self.grant(committed_date=self.today + timedelta(days=1))

        self.overdue.refresh_from_db()

        self.assertTrue(self.overdue.is_protected_from_cut(on=self.today))
        self.assertFalse(
            self.overdue.is_protected_from_cut(on=self.today + timedelta(days=5))
        )

    def test_cancelling_it_returns_the_charge_to_the_cut_path(self):
        commitment = self.grant()

        commitment.cancel(user=self.cashier, reason="El abonado se retractó.")
        self.overdue.refresh_from_db()

        self.assertEqual(commitment.status, PaymentCommitment.Status.CANCELLED)
        self.assertFalse(self.overdue.is_protected_from_cut())
        self.assertIn("se retractó", commitment.reason)

    def test_it_is_not_cancelled_twice(self):
        commitment = self.grant()
        commitment.cancel(user=self.cashier, reason="Primera anulación.")

        with self.assertRaises(ValidationError):
            commitment.cancel(user=self.cashier, reason="Segunda.")


class CommitmentWebTests(CommitmentTestCase):
    def setUp(self):
        super().setUp()

        self.viewer = self.make_user("consulta1", permissions=["view_charge"])
        self.granter = self.make_user(
            "supervisor1",
            permissions=["view_charge", "grant_paymentcommitment"],
        )

    def url(self):
        return reverse("payments:commitment_create", args=[self.customer.pk])

    def test_viewing_the_debt_does_not_grant_committing(self):
        """Aplazar un corte es una decisión comercial, no una consulta."""
        self.login(self.viewer)

        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_the_debt_board_hides_the_button_without_permission(self):
        self.login(self.viewer)

        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertFalse(response.context["can_grant_commitment"])
        self.assertNotContains(response, self.url())

    def test_the_debt_board_offers_the_button_to_who_may_grant(self):
        self.login(self.granter)

        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertTrue(response.context["can_grant_commitment"])
        self.assertContains(response, self.url())

    def test_selected_charges_are_committed(self):
        self.login(self.granter)

        response = self.client.post(
            self.url(),
            {
                "charges": [self.overdue.pk],
                "committed_date": (self.today + timedelta(days=5)).isoformat(),
                "reason": "El abonado cobra el viernes.",
            },
        )

        commitment = PaymentCommitment.objects.get()

        self.assertRedirects(
            response, reverse("payments:debt", args=[self.customer.pk])
        )
        self.assertEqual(list(commitment.charges.all()), [self.overdue])
        self.assertEqual(commitment.granted_by, self.granter)

    def test_submitting_without_selecting_a_charge_reports_it(self):
        self.login(self.granter)

        response = self.client.post(
            self.url(),
            {
                "committed_date": (self.today + timedelta(days=5)).isoformat(),
                "reason": "Sin elegir nada.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "al menos un cargo")
        self.assertFalse(PaymentCommitment.objects.exists())

    def test_a_past_date_does_not_create_the_commitment(self):
        self.login(self.granter)

        response = self.client.post(
            self.url(),
            {
                "charges": [self.overdue.pk],
                "committed_date": (self.today - timedelta(days=1)).isoformat(),
                "reason": "Fecha ya pasada.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PaymentCommitment.objects.exists())

    def test_the_board_shows_the_active_commitment(self):
        self.grant()
        self.login(self.granter)

        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertEqual(len(response.context["active_commitments"]), 1)
        self.assertContains(response, "Compromiso de pago vigente")

    def test_the_commitment_is_read_before_deciding_what_to_collect(self):
        """El aviso encabeza la pantalla, como la OT abierta en la de ordenes.

        Mientras el compromiso siga en pie cambia lo que el operador puede
        decirle al abonado -esa deuda no empuja al corte hasta la fecha
        acordada-, y al pie se leia despues de haber marcado que cobrar.
        """
        self.grant()
        self.login(self.granter)

        body = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        ).content.decode()

        self.assertLess(
            body.index("Compromiso de pago vigente"),
            body.index('id="deudasForm"'),
        )

    def test_cancelling_from_the_board_requires_the_permission(self):
        commitment = self.grant()
        self.login(self.viewer)

        response = self.client.post(
            reverse("payments:commitment_cancel", args=[commitment.pk])
        )
        commitment.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(commitment.status, PaymentCommitment.Status.ACTIVE)
