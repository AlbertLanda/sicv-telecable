"""
Caja: aplicar el dinero recibido, emitir el recibo y poder deshacerlo.

Lo que se fija aquí es que el pago y la deuda no se puedan separar: registrar
un cobro cierra los cargos que cubre, y anularlo se los devuelve. Si esas dos
mitades pudieran ocurrir por separado, la deuda del abonado dejaría de
explicarse con su historial.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.payments.models import Charge, Payment, Receipt
from apps.payments.services import register_payment
from apps.payments.tests.base import PaymentsTestCase


class PaymentTestCase(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.august = self.make_charge(
            description="Mensualidad 08/2026",
            period=date(2026, 8, 1),
            due_date=date(2026, 8, 31),
        )
        self.september = self.make_charge(
            description="Mensualidad 09/2026",
            period=date(2026, 9, 1),
            due_date=date(2026, 9, 30),
        )

    def make_charge(self, **overrides):
        data = {
            "customer": self.customer,
            "subscription": self.subscription,
            "concept": Charge.Concept.MONTHLY,
            "amount": Decimal("80.00"),
        }
        data.update(overrides)

        return Charge.objects.create(**data)

    def pay(self, amount, **kwargs):
        kwargs.setdefault("method", Payment.Method.CASH)

        return register_payment(
            customer=self.customer,
            amount=Decimal(amount),
            branch=self.branch,
            user=self.cashier,
            **kwargs,
        )


class PaymentAllocationTests(PaymentTestCase):
    def test_without_an_explicit_split_it_pays_the_oldest_first(self):
        """Lo que hace un cajero cuando el abonado paga «a cuenta».

        Primero se limpia lo más viejo, que es lo que puede llevar al abonado
        al corte. Aplicarlo al mes más reciente dejaría vencido el que ya
        estaba en riesgo.
        """
        payment, _ = self.pay("80.00")

        self.august.refresh_from_db()
        self.september.refresh_from_db()

        self.assertEqual(self.august.status, Charge.Status.PAID)
        self.assertEqual(self.september.status, Charge.Status.PENDING)
        self.assertEqual(payment.allocations.count(), 1)

    def test_a_partial_amount_leaves_the_charge_partially_paid(self):
        self.pay("30.00")

        self.august.refresh_from_db()

        self.assertEqual(self.august.status, Charge.Status.PARTIALLY_PAID)
        self.assertEqual(self.august.balance, Decimal("50.00"))

    def test_one_payment_can_cover_several_months(self):
        payment, _ = self.pay("160.00")

        self.august.refresh_from_db()
        self.september.refresh_from_db()

        self.assertEqual(payment.allocations.count(), 2)
        self.assertEqual(self.august.status, Charge.Status.PAID)
        self.assertEqual(self.september.status, Charge.Status.PAID)

    def test_an_explicit_split_pays_the_month_the_operator_chose(self):
        """El cajero puede decir «esto es la mensualidad de septiembre».

        El reparto automático es una comodidad, no una imposición: si el
        abonado pide cubrir un mes concreto, el sistema tiene que respetarlo.
        """
        self.pay("80.00", allocations=[(self.september, Decimal("80.00"))])

        self.august.refresh_from_db()
        self.september.refresh_from_db()

        self.assertEqual(self.august.status, Charge.Status.PENDING)
        self.assertEqual(self.september.status, Charge.Status.PAID)

    def test_the_surplus_stays_as_credit_on_the_payment(self):
        """Lo que sobra no inventa un cargo.

        Un cargo creado para absorber el excedente sería deuda que el abonado
        nunca contrajo, y aparecería en su estado de cuenta como tal.
        """
        payment, _ = self.pay("200.00")

        self.assertEqual(payment.allocated_amount, Decimal("160.00"))
        self.assertEqual(payment.unallocated_amount, Decimal("40.00"))

    def test_applying_more_than_the_balance_is_rejected(self):
        with self.assertRaises(ValidationError) as error:
            self.pay("500.00", allocations=[(self.august, Decimal("200.00"))])

        self.assertIn("saldo", str(error.exception))

    def test_applying_more_than_what_was_received_is_rejected(self):
        """No se puede cubrir con S/ 50 dos meses de S/ 80.

        Sin esta regla el sistema cancelaría deuda que nadie pagó.
        """
        with self.assertRaises(ValidationError) as error:
            self.pay(
                "50.00",
                allocations=[
                    (self.august, Decimal("40.00")),
                    (self.september, Decimal("40.00")),
                ],
            )

        self.assertIn("supera el monto recibido", str(error.exception))

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
        foreign_charge = Charge.objects.create(
            customer=other,
            concept=Charge.Concept.OTHER,
            description="Cargo ajeno",
            amount=Decimal("50.00"),
            due_date=date(2026, 9, 30),
        )

        with self.assertRaises(ValidationError):
            self.pay("50.00", allocations=[(foreign_charge, Decimal("50.00"))])

    def test_a_zero_amount_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.pay("0.00")


class PaymentMethodTests(PaymentTestCase):
    def test_a_digital_method_requires_its_operation_number(self):
        """Yape y transferencia se concilian con el número de operación.

        Sin él no hay forma de cruzar el cobro con el estado de cuenta del
        banco, y el pago queda sin respaldo.
        """
        with self.assertRaises(ValidationError) as error:
            self.pay("80.00", method=Payment.Method.YAPE)

        self.assertIn("reference", error.exception.error_dict)

    def test_cash_does_not_require_a_reference(self):
        payment, _ = self.pay("80.00", method=Payment.Method.CASH)

        self.assertEqual(payment.reference, "")

    def test_a_digital_method_with_its_reference_is_accepted(self):
        payment, _ = self.pay(
            "80.00", method=Payment.Method.YAPE, reference="00099887"
        )

        self.assertEqual(payment.method, Payment.Method.YAPE)
        self.assertEqual(payment.reference, "00099887")


class ReceiptTests(PaymentTestCase):
    def test_every_payment_gets_its_receipt(self):
        payment, receipt = self.pay("80.00")

        self.assertEqual(receipt.payment, payment)
        self.assertEqual(receipt.number, 1)

    def test_the_number_advances_and_never_repeats(self):
        """El correlativo sale de una fila bloqueada, no del último recibo.

        Deducirlo leyendo el máximo daría el mismo número a dos cajas que
        cobran a la vez, y dos abonados se llevarían el mismo comprobante.
        """
        _, first = self.pay("40.00")
        _, second = self.pay("40.00")

        self.assertEqual([first.number, second.number], [1, 2])
        self.assertEqual(Receipt.objects.count(), 2)

    def test_the_full_number_is_padded_for_reading(self):
        _, receipt = self.pay("80.00")

        self.assertEqual(receipt.full_number, "R001-000001")


class PaymentVoidTests(PaymentTestCase):
    def test_voiding_returns_the_debt(self):
        payment, _ = self.pay("80.00")

        payment.void(user=self.cashier, reason="Cobro duplicado en ventanilla.")

        self.august.refresh_from_db()

        self.assertEqual(payment.status, Payment.Status.VOIDED)
        self.assertEqual(self.august.status, Charge.Status.PENDING)
        self.assertEqual(self.august.balance, Decimal("80.00"))

    def test_the_payment_is_not_deleted(self):
        """Anular deja rastro; borrar lo escondería.

        El historial tiene que poder explicar que hubo un cobro y que se
        deshizo, con su motivo y su responsable.
        """
        payment, _ = self.pay("80.00")

        payment.void(user=self.cashier, reason="Error de digitación.")

        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
        self.assertEqual(payment.void_reason, "Error de digitación.")
        self.assertEqual(payment.voided_by, self.cashier)
        self.assertIsNotNone(payment.voided_at)

    def test_voiding_without_a_reason_is_rejected(self):
        payment, _ = self.pay("80.00")

        with self.assertRaises(ValidationError):
            payment.void(user=self.cashier, reason="   ")

    def test_a_payment_is_not_voided_twice(self):
        payment, _ = self.pay("80.00")
        payment.void(user=self.cashier, reason="Primera anulación.")

        with self.assertRaises(ValidationError):
            payment.void(user=self.cashier, reason="Segunda anulación.")

    def test_the_receipt_of_a_voided_payment_stops_crediting(self):
        payment, receipt = self.pay("80.00")

        payment.void(user=self.cashier, reason="Cobro anulado.")
        receipt.refresh_from_db()

        self.assertTrue(receipt.is_voided)
