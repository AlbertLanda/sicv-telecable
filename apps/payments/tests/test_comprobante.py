"""
El comprobante de cobro: serie, cobrador, descuento por fila y pendiente.

Lo que se fija aquí es que un comprobante emitido como **pendiente** no baje
la deuda. Es la confusión que haría perder dinero: si un pendiente descontara
el saldo, el abonado quedaría al día sin que el dinero hubiera entrado.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.payments.models import (
    Charge,
    Payment,
    PaymentAllocation,
    Receipt,
    ReceiptSequence,
)
from apps.payments.services import (
    authorizer_options,
    collector_options,
    discount_for,
    receipt_sequence,
    receipt_series_options,
    register_payment,
)
from apps.payments.tests.base import PaymentsTestCase


class ComprobanteTestCase(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()

        # Con pronto pago vigente: S/ 79 de monto, S/ 10 de descuento.
        self.discounted = Charge.objects.create(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            description="PLAN INTERNET ESTANDAR 600MG - 2026",
            issued_on=self.today,
            period=date(self.today.year, self.today.month, 1),
            amount=Decimal("79.00"),
            due_date=self.today + timedelta(days=10),
            early_discount=Decimal("10.00"),
            discount_deadline=self.today + timedelta(days=8),
        )

        self.plain = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.REACTIVATION,
            description="RECONEXIÓN DE SERVICIO",
            issued_on=self.today,
            amount=Decimal("20.00"),
            due_date=self.today + timedelta(days=15),
        )


class ChargeDisplayTests(ComprobanteTestCase):
    def test_the_period_reads_as_a_range(self):
        """La pantalla muestra «01/09/2026 - 30/09/2026», no un mes suelto."""
        self.discounted.period_end = date(self.today.year, self.today.month, 30)
        self.discounted.save()

        self.assertIn(" - ", self.discounted.period_label)

    def test_a_charge_without_a_period_has_no_range(self):
        self.assertEqual(self.plain.period_label, "")

    def test_the_current_discount_expires_with_the_deadline(self):
        """El descuento de la columna se apaga solo al pasar el plazo.

        Se calcula contra el día, así que nadie tiene que editar el cargo
        para que deje de ofrecer un pronto pago que ya se perdió.
        """
        self.assertEqual(self.discounted.current_discount, Decimal("10.00"))

        self.discounted.discount_deadline = self.today - timedelta(days=1)
        self.discounted.save()

        self.assertEqual(self.discounted.current_discount, Decimal("0.00"))

    def test_the_document_column_is_empty_until_it_is_charged(self):
        self.assertEqual(self.discounted.paying_receipts, [])

    def test_the_document_column_shows_the_receipt_that_paid_it(self):
        _, receipt = register_payment(
            customer=self.customer,
            amount=Decimal("69.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.discounted, Decimal("69.00"))],
        )

        self.discounted.refresh_from_db()

        self.assertEqual(
            [item.pk for item in self.discounted.paying_receipts], [receipt.pk]
        )

    def test_a_voided_receipt_stops_appearing_as_the_document(self):
        """Un cobro anulado deja de acreditar la deuda, y su papel también."""
        payment, _ = register_payment(
            customer=self.customer,
            amount=Decimal("69.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.discounted, Decimal("69.00"))],
        )
        payment.void(user=self.cashier, reason="Cobro duplicado.")

        self.discounted.refresh_from_db()

        self.assertEqual(self.discounted.paying_receipts, [])


class AllocationDiscountTests(ComprobanteTestCase):
    def test_paying_in_full_within_the_window_records_the_discount(self):
        """El comprobante explica por qué S/ 79 se cerró con S/ 69."""
        register_payment(
            customer=self.customer,
            amount=Decimal("69.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.discounted, Decimal("69.00"))],
        )

        allocation = PaymentAllocation.objects.get(charge=self.discounted)

        self.assertEqual(allocation.amount, Decimal("69.00"))
        self.assertEqual(allocation.discount, Decimal("10.00"))
        self.assertEqual(allocation.gross_amount, Decimal("79.00"))

    def test_a_partial_payment_does_not_win_the_discount(self):
        """Pagar S/ 1 dentro del plazo no rebaja el mes entero."""
        register_payment(
            customer=self.customer,
            amount=Decimal("1.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.discounted, Decimal("1.00"))],
        )

        allocation = PaymentAllocation.objects.get(charge=self.discounted)

        self.assertEqual(allocation.discount, Decimal("0.00"))

    def test_a_charge_without_a_discount_records_none(self):
        register_payment(
            customer=self.customer,
            amount=Decimal("20.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.plain, Decimal("20.00"))],
        )

        allocation = PaymentAllocation.objects.get(charge=self.plain)

        self.assertEqual(allocation.discount, Decimal("0.00"))

    def test_the_helper_reports_no_discount_past_the_deadline(self):
        self.discounted.discount_deadline = self.today - timedelta(days=1)
        self.discounted.save()

        self.assertEqual(
            discount_for(self.discounted, Decimal("79.00")), Decimal("0.00")
        )


class PendingPaymentTests(ComprobanteTestCase):
    def test_a_pending_receipt_does_not_lower_the_debt(self):
        """«Cancelado: No» emite el papel sin que el dinero haya entrado.

        Si bajara la deuda, el abonado quedaría al día sin haber pagado y el
        corte no lo alcanzaría.
        """
        payment, receipt = register_payment(
            customer=self.customer,
            amount=Decimal("20.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.plain, Decimal("20.00"))],
            settled=False,
        )

        self.plain.refresh_from_db()

        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertIsNone(payment.paid_at)
        self.assertEqual(self.plain.status, Charge.Status.PENDING)
        self.assertEqual(self.plain.balance, Decimal("20.00"))
        self.assertTrue(Receipt.objects.filter(pk=receipt.pk).exists())

    def test_confirming_it_is_what_lowers_the_debt(self):
        payment, _ = register_payment(
            customer=self.customer,
            amount=Decimal("20.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.plain, Decimal("20.00"))],
            settled=False,
        )

        payment.confirm()
        self.plain.refresh_from_db()

        self.assertEqual(payment.status, Payment.Status.REGISTERED)
        self.assertIsNotNone(payment.paid_at)
        self.assertEqual(self.plain.status, Charge.Status.PAID)

    def test_a_settled_payment_cannot_be_confirmed_again(self):
        payment, _ = register_payment(
            customer=self.customer,
            amount=Decimal("20.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.plain, Decimal("20.00"))],
        )

        with self.assertRaises(ValidationError):
            payment.confirm()

    def test_a_settled_payment_records_when_the_money_arrived(self):
        payment, _ = register_payment(
            customer=self.customer,
            amount=Decimal("20.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.plain, Decimal("20.00"))],
        )

        self.assertEqual(payment.status, Payment.Status.REGISTERED)
        self.assertIsNotNone(payment.paid_at)


class CollectorAndSeriesTests(ComprobanteTestCase):
    def test_the_collector_is_recorded_apart_from_the_user(self):
        """Quien trajo el dinero y quien lo asentó pueden ser distintos.

        Guardar solo al usuario haría imposible cuadrar por cobrador, que es
        como se liquida a un vendedor que cobró en campo.
        """
        seller = self.make_user("vendedor1", role=User.Role.SALES)

        payment, _ = register_payment(
            customer=self.customer,
            amount=Decimal("20.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            collector=seller,
            allocations=[(self.plain, Decimal("20.00"))],
        )

        self.assertEqual(payment.received_by, self.cashier)
        self.assertEqual(payment.collector, seller)

    def test_only_sales_users_are_offered_as_collectors(self):
        seller = self.make_user("vendedor1", role=User.Role.SALES)
        technician = self.make_user("tecnico1", role=User.Role.TECHNICIAN)

        offered = list(collector_options())

        self.assertIn(seller, offered)
        self.assertNotIn(technician, offered)

    def test_an_inactive_seller_is_not_offered(self):
        seller = self.make_user("vendedor2", role=User.Role.SALES)
        seller.is_active = False
        seller.save()

        self.assertNotIn(seller, list(collector_options()))

    def test_the_window_is_never_left_without_a_book(self):
        """La ventanilla nunca debe quedarse sin talonario con el que cobrar."""
        series = receipt_series_options()

        self.assertTrue(series)

    def test_the_systems_own_book_is_no_longer_offered(self):
        """R001 se usó mientras no había padrón y no vuelve a la ventanilla.

        Donde ya existe no se borra -sus comprobantes se entregaron y tienen
        que poder seguir explicándose-, y donde no, no se crea para rellenar
        la lista. En ninguno de los dos casos se ofrece para cobrar.
        """
        codes = [item.code for item in receipt_series_options()]

        self.assertNotIn("R001", codes)

    def test_a_book_created_on_the_fly_is_born_retired(self):
        """Llegar a crearlo significa que nadie lo eligió en la ventanilla.

        Ofrecerlo después pondría a elegir un block que no existe en papel.
        """
        receipt_sequence("NOEXISTE")

        sequence = ReceiptSequence.objects.get(code="NOEXISTE")

        self.assertFalse(sequence.is_active)
        self.assertNotIn(
            "NOEXISTE",
            [item.code for item in receipt_series_options()],
        )

    def test_only_deciding_roles_are_offered_as_authorizers(self):
        supervisor = self.make_user("super1", role=User.Role.SUPERVISOR)
        seller = self.make_user("vendedor1", role=User.Role.SALES)

        offered = list(authorizer_options())

        self.assertIn(supervisor, offered)
        self.assertNotIn(seller, offered)


class ComprobanteWebTests(ComprobanteTestCase):
    def setUp(self):
        super().setUp()

        self.cashier_user = self.make_user(
            "ventanilla1", permissions=["view_charge", "add_payment"]
        )

    def register_url(self):
        return reverse("payments:register", args=[self.customer.pk])

    def test_the_screen_shows_the_selected_rows_with_their_discount(self):
        self.login(self.cashier_user)

        response = self.client.get(
            self.register_url(), {"charges": [self.discounted.pk]}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_gross"], Decimal("79.00"))
        self.assertEqual(response.context["selected_discount"], Decimal("10.00"))
        self.assertEqual(response.context["selected_total"], Decimal("69.00"))

    def test_the_screen_offers_every_payment_method_of_the_legacy_form(self):
        self.login(self.cashier_user)

        response = self.client.get(self.register_url())
        offered = [
            value
            for value, _ in response.context["form"].fields["method"].choices
        ]

        for method in (
            Payment.Method.CASH,
            Payment.Method.DEPOSIT,
            Payment.Method.TRANSFER,
            Payment.Method.CARD,
            Payment.Method.CHEQUE,
            Payment.Method.YAPE,
            Payment.Method.PLIN,
        ):
            self.assertIn(method, offered)

    def test_charging_as_pending_leaves_the_debt_standing(self):
        self.login(self.cashier_user)

        self.client.post(
            self.register_url(),
            {
                "amount": "20.00",
                "method": Payment.Method.CASH,
                "charges": [self.plain.pk],
                "settled": "0",
            },
        )

        payment = Payment.objects.get()
        self.plain.refresh_from_db()

        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(self.plain.status, Charge.Status.PENDING)

    def test_charging_as_settled_closes_the_debt(self):
        self.login(self.cashier_user)

        self.client.post(
            self.register_url(),
            {
                "amount": "20.00",
                "method": Payment.Method.CASH,
                "charges": [self.plain.pk],
                "settled": "1",
            },
        )

        self.plain.refresh_from_db()

        self.assertEqual(self.plain.status, Charge.Status.PAID)

    def test_a_cheque_requires_its_operation_number(self):
        self.login(self.cashier_user)

        response = self.client.post(
            self.register_url(),
            {
                "amount": "20.00",
                "method": Payment.Method.CHEQUE,
                "charges": [self.plain.pk],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Payment.objects.exists())
