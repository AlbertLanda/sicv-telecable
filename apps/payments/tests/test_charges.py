"""
Reglas del cargo: cuánto se debe, desde cuándo está vencido y qué lo cierra.

Lo que se fija aquí es que el monto a pagar dependa del *día* en que se paga y
no de un campo que alguien edite: el pronto pago se pierde solo al pasar la
fecha, y esa es la regla que la caja no debe poder saltarse.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from apps.payments.models import Charge
from apps.payments.tests.base import PaymentsTestCase


class ChargeAmountTests(PaymentsTestCase):
    def make_charge(self, **overrides):
        data = {
            "customer": self.customer,
            "subscription": self.subscription,
            "concept": Charge.Concept.MONTHLY,
            "description": "Mensualidad 09/2026",
            "period": date(2026, 9, 1),
            "amount": Decimal("80.00"),
            "due_date": date(2026, 9, 30),
            "early_discount": Decimal("5.00"),
            "discount_deadline": date(2026, 9, 10),
        }
        data.update(overrides)

        return Charge.objects.create(**data)

    def test_before_the_deadline_the_discount_applies(self):
        charge = self.make_charge()

        self.assertEqual(charge.amount_due_on(date(2026, 9, 5)), Decimal("75.00"))

    def test_on_the_deadline_the_discount_still_applies(self):
        """El día límite cuenta como pronto pago.

        Es el borde que decide si un abonado que paga el día 10 recibe o no el
        descuento; dejarlo implícito haría que cambiara al reescribir la
        comparación.
        """
        charge = self.make_charge()

        self.assertEqual(charge.amount_due_on(date(2026, 9, 10)), Decimal("75.00"))

    def test_after_the_deadline_the_full_amount_is_owed(self):
        charge = self.make_charge()

        self.assertEqual(charge.amount_due_on(date(2026, 9, 11)), Decimal("80.00"))

    def test_a_charge_without_discount_always_costs_the_same(self):
        charge = self.make_charge(early_discount=0, discount_deadline=None)

        self.assertEqual(charge.amount_due_on(date(2026, 9, 5)), Decimal("80.00"))
        self.assertEqual(charge.amount_due_on(date(2026, 12, 5)), Decimal("80.00"))

    def test_the_balance_never_goes_negative(self):
        """Pagar de más no genera un saldo negativo en el cargo.

        El excedente es del pago -queda como saldo a favor-, no del cargo: un
        cargo con saldo negativo restaría deuda de otros meses sin que nadie
        lo haya decidido.
        """
        charge = self.make_charge()
        self.pay(charge, Decimal("80.00"), day=date(2026, 9, 5))

        self.assertEqual(charge.balance_on(date(2026, 9, 5)), Decimal("0.00"))

    def pay(self, charge, amount, day=None):
        from apps.payments.services import register_payment

        return register_payment(
            customer=charge.customer,
            amount=amount,
            method="CASH",
            branch=self.branch,
            user=self.cashier,
            allocations=[(charge, min(amount, charge.balance_on(day)))],
            day=day,
        )


class ChargeStatusTests(PaymentsTestCase):
    def make_charge(self, **overrides):
        data = {
            "customer": self.customer,
            "subscription": self.subscription,
            "concept": Charge.Concept.MONTHLY,
            "description": "Mensualidad 09/2026",
            "period": date(2026, 9, 1),
            "amount": Decimal("80.00"),
            "due_date": date(2026, 9, 30),
        }
        data.update(overrides)

        return Charge.objects.create(**data)

    def test_a_new_charge_is_pending(self):
        charge = self.make_charge()

        self.assertEqual(charge.status, Charge.Status.PENDING)
        self.assertEqual(charge.balance, Decimal("80.00"))

    def test_it_is_overdue_only_after_the_due_date(self):
        charge = self.make_charge()

        self.assertFalse(charge.is_overdue(date(2026, 9, 30)))
        self.assertTrue(charge.is_overdue(date(2026, 10, 1)))

    def test_a_cancelled_charge_keeps_its_status(self):
        """Anular un cargo es una decisión, no un cálculo.

        refresh_status() recalcula a partir de lo pagado; si pudiera revivir
        un cargo anulado, cualquier movimiento posterior devolvería al abonado
        una deuda que alguien decidió quitarle.
        """
        charge = self.make_charge(status=Charge.Status.CANCELLED)

        self.assertEqual(charge.refresh_status(), Charge.Status.CANCELLED)


class ChargeValidationTests(PaymentsTestCase):
    def test_a_monthly_charge_needs_its_period(self):
        charge = Charge(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            description="Mensualidad sin mes",
            amount=Decimal("80.00"),
            due_date=date(2026, 9, 30),
        )

        with self.assertRaises(ValidationError) as error:
            charge.full_clean()

        self.assertIn("period", error.exception.error_dict)

    def test_the_period_is_stored_as_the_first_day_of_the_month(self):
        charge = Charge(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            description="Mensualidad 09/2026",
            period=date(2026, 9, 15),
            amount=Decimal("80.00"),
            due_date=date(2026, 9, 30),
        )

        with self.assertRaises(ValidationError) as error:
            charge.full_clean()

        self.assertIn("period", error.exception.error_dict)

    def test_a_discount_cannot_reach_the_amount(self):
        charge = Charge(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            description="Mensualidad 09/2026",
            period=date(2026, 9, 1),
            amount=Decimal("80.00"),
            due_date=date(2026, 9, 30),
            early_discount=Decimal("80.00"),
            discount_deadline=date(2026, 9, 10),
        )

        with self.assertRaises(ValidationError) as error:
            charge.full_clean()

        self.assertIn("early_discount", error.exception.error_dict)

    def test_a_discount_needs_its_deadline(self):
        charge = Charge(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            description="Mensualidad 09/2026",
            period=date(2026, 9, 1),
            amount=Decimal("80.00"),
            due_date=date(2026, 9, 30),
            early_discount=Decimal("5.00"),
        )

        with self.assertRaises(ValidationError) as error:
            charge.full_clean()

        self.assertIn("discount_deadline", error.exception.error_dict)

    def test_the_same_month_cannot_be_charged_twice(self):
        """La garantía de que regenerar cargos no duplica deuda.

        Se comprueba contra la base y no contra el servicio: si la restricción
        desaparece, el servicio seguiría filtrando bien en condiciones
        normales y el error solo aparecería con dos procesos a la vez.
        """
        common = {
            "customer": self.customer,
            "subscription": self.subscription,
            "concept": Charge.Concept.MONTHLY,
            "period": date(2026, 9, 1),
            "amount": Decimal("80.00"),
            "due_date": date(2026, 9, 30),
        }

        Charge.objects.create(description="Mensualidad 09/2026", **common)

        with self.assertRaises(IntegrityError):
            Charge.objects.create(description="Mensualidad repetida", **common)
