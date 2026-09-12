"""
Las tres pantallas de la cuenta del abonado y el cobro en ventanilla.

Lo que se fija aquí es el acceso y lo que cada pantalla afirma. Consultar la
deuda, ver el historial y anular un cobro son capacidades distintas: quien
atiende la ventanilla puede cobrar, pero deshacer lo cobrado es otra decisión.
"""

from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.payments.models import Charge, Payment, Receipt
from apps.payments.services import register_payment
from apps.payments.tests.base import PaymentsTestCase


class AccountScreensTestCase(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            description="Mensualidad 08/2026",
            period=date(2026, 8, 1),
            amount=Decimal("80.00"),
            due_date=date(2026, 8, 31),
        )

        self.viewer = self.make_user(
            "consulta1",
            permissions=["view_charge", "view_payment", "view_receipt"],
        )
        self.cashier_user = self.make_user(
            "ventanilla1",
            permissions=[
                "view_charge",
                "view_payment",
                "view_receipt",
                "add_payment",
            ],
        )
        self.supervisor = self.make_user(
            "supervisor1",
            permissions=[
                "view_charge",
                "view_payment",
                "view_receipt",
                "add_payment",
                "void_payment",
            ],
        )

    def debt_url(self):
        return reverse("payments:debt", args=[self.customer.pk])

    def history_url(self):
        return reverse("payments:history", args=[self.customer.pk])

    def receipts_url(self):
        return reverse("payments:receipts", args=[self.customer.pk])

    def register_url(self):
        return reverse("payments:register", args=[self.customer.pk])


class DebtScreenTests(AccountScreensTestCase):
    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.debt_url())

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_without_permission_it_is_forbidden(self):
        """403 y no una cuenta vacía.

        Una pantalla en blanco diría «no debe nada», que es falso y distinto
        de «no puede consultarlo».
        """
        self.login(self.make_user("sinpermiso"))

        self.assertEqual(self.client.get(self.debt_url()).status_code, 403)

    def test_an_unknown_customer_is_not_revealed_to_the_unauthorized(self):
        """Sin permiso se responde 403 aunque el abonado no exista.

        Si la búsqueda corriera antes del control de acceso, la diferencia
        entre 403 y 404 diría qué códigos de cliente existen.
        """
        self.login(self.make_user("sinpermiso2"))

        url = reverse("payments:debt", args=[self.customer.pk + 999])

        self.assertEqual(self.client.get(url).status_code, 403)

    def test_it_lists_the_outstanding_charges_and_the_total(self):
        self.login(self.viewer)

        response = self.client.get(self.debt_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mensualidad 08/2026")
        self.assertEqual(response.context["debt"]["total"], Decimal("80.00"))

    def test_a_customer_without_charges_is_told_so(self):
        self.charge.delete()
        self.login(self.viewer)

        response = self.client.get(self.debt_url())

        self.assertContains(response, "no tiene deudas pendientes")

    def test_consulting_does_not_grant_charging(self):
        """Ver la deuda y cobrarla son permisos distintos."""
        self.login(self.viewer)

        response = self.client.get(self.debt_url())

        self.assertFalse(response.context["can_register_payment"])
        self.assertNotContains(response, self.register_url())

    def test_the_cashier_sees_the_charge_action(self):
        self.login(self.cashier_user)

        response = self.client.get(self.debt_url())

        self.assertTrue(response.context["can_register_payment"])
        self.assertContains(response, self.register_url())


class PaymentHistoryScreenTests(AccountScreensTestCase):
    def test_without_permission_it_is_forbidden(self):
        self.login(self.make_user("sinpermiso"))

        self.assertEqual(self.client.get(self.history_url()).status_code, 403)

    def test_it_shows_the_payment_with_what_it_covered(self):
        register_payment(
            customer=self.customer,
            amount=Decimal("80.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
        )

        self.login(self.viewer)
        response = self.client.get(self.history_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mensualidad 08/2026")
        self.assertContains(response, "R001-0000001")

    def test_a_voided_payment_stays_visible(self):
        """El historial no esconde lo anulado.

        Un cobro que desaparece deja un hueco sin explicación justo donde el
        abonado va a preguntar qué pasó con su dinero.
        """
        payment, _ = register_payment(
            customer=self.customer,
            amount=Decimal("80.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
        )
        payment.void(user=self.cashier, reason="Cobro duplicado.")

        self.login(self.viewer)
        response = self.client.get(self.history_url())

        self.assertContains(response, "Anulado")
        self.assertContains(response, "Cobro duplicado.")

    def test_viewing_the_history_does_not_grant_voiding(self):
        self.login(self.viewer)

        response = self.client.get(self.history_url())

        self.assertFalse(response.context["can_void_payment"])


class ReceiptsScreenTests(AccountScreensTestCase):
    def test_without_permission_it_is_forbidden(self):
        self.login(self.make_user("sinpermiso"))

        self.assertEqual(self.client.get(self.receipts_url()).status_code, 403)

    def test_it_lists_the_issued_receipts(self):
        register_payment(
            customer=self.customer,
            amount=Decimal("80.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
        )

        self.login(self.viewer)
        response = self.client.get(self.receipts_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "R001-0000001")

    def test_the_receipt_of_a_voided_payment_is_marked(self):
        payment, receipt = register_payment(
            customer=self.customer,
            amount=Decimal("80.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
        )
        payment.void(user=self.cashier, reason="Error de caja.")

        self.login(self.viewer)
        response = self.client.get(
            reverse("payments:receipt_detail", args=[receipt.pk])
        )

        self.assertContains(response, "Comprobante anulado")
        self.assertContains(response, "Error de caja.")


class PaymentRegisterTests(AccountScreensTestCase):
    def test_without_permission_it_is_forbidden(self):
        self.login(self.viewer)

        self.assertEqual(self.client.get(self.register_url()).status_code, 403)

    def test_a_cash_payment_is_registered_and_redirects_to_its_receipt(self):
        self.login(self.cashier_user)

        response = self.client.post(
            self.register_url(),
            {"amount": "80.00", "method": Payment.Method.CASH},
        )

        payment = Payment.objects.get()
        receipt = Receipt.objects.get()

        self.assertRedirects(
            response, reverse("payments:receipt_detail", args=[receipt.pk])
        )
        self.assertEqual(payment.amount, Decimal("80.00"))
        self.assertEqual(payment.received_by, self.cashier_user)
        self.assertEqual(payment.branch, self.branch)

        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, Charge.Status.PAID)

    def test_a_digital_method_without_its_reference_is_rejected(self):
        self.login(self.cashier_user)

        response = self.client.post(
            self.register_url(),
            {"amount": "80.00", "method": Payment.Method.YAPE},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "número de operación")
        self.assertFalse(Payment.objects.exists())

    def test_the_operator_can_choose_which_charge_to_cover(self):
        september = Charge.objects.create(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            description="Mensualidad 09/2026",
            period=date(2026, 9, 1),
            amount=Decimal("80.00"),
            due_date=date(2026, 9, 30),
        )

        self.login(self.cashier_user)
        self.client.post(
            self.register_url(),
            {
                "amount": "80.00",
                "method": Payment.Method.CASH,
                f"charge_{september.pk}": "80.00",
            },
        )

        self.charge.refresh_from_db()
        september.refresh_from_db()

        self.assertEqual(self.charge.status, Charge.Status.PENDING)
        self.assertEqual(september.status, Charge.Status.PAID)

    def test_applying_more_than_the_balance_does_not_register_anything(self):
        """El rechazo del dominio se muestra sin dejar el cobro a medias."""
        self.login(self.cashier_user)

        response = self.client.post(
            self.register_url(),
            {
                "amount": "500.00",
                "method": Payment.Method.CASH,
                f"charge_{self.charge.pk}": "500.00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(Receipt.objects.exists())

        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, Charge.Status.PENDING)


class PaymentVoidWebTests(AccountScreensTestCase):
    def make_payment(self):
        payment, _ = register_payment(
            customer=self.customer,
            amount=Decimal("80.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
        )

        return payment

    def test_charging_does_not_grant_voiding(self):
        payment = self.make_payment()
        self.login(self.cashier_user)

        response = self.client.post(
            reverse("payments:void", args=[payment.pk]),
            {"reason": "Me equivoqué."},
        )

        payment.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(payment.status, Payment.Status.REGISTERED)

    def test_the_supervisor_voids_and_the_debt_returns(self):
        payment = self.make_payment()
        self.login(self.supervisor)

        response = self.client.post(
            reverse("payments:void", args=[payment.pk]),
            {"reason": "Cobro duplicado en ventanilla."},
        )

        payment.refresh_from_db()
        self.charge.refresh_from_db()

        self.assertRedirects(response, self.history_url())
        self.assertEqual(payment.status, Payment.Status.VOIDED)
        self.assertEqual(self.charge.status, Charge.Status.PENDING)

    def test_voiding_without_a_reason_changes_nothing(self):
        payment = self.make_payment()
        self.login(self.supervisor)

        self.client.post(reverse("payments:void", args=[payment.pk]), {"reason": "  "})

        payment.refresh_from_db()

        self.assertEqual(payment.status, Payment.Status.REGISTERED)
