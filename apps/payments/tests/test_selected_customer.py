"""
Cómo se elige el abonado cuya cuenta muestran Deuda, Historial y Comprobantes.

El buscador enlaza directamente a la ficha, así que «el abonado seleccionado»
tiene que significar «el último cuya ficha abrí». Cuando eso dependía del
botón «Usar cliente» -que la ficha nueva ya no muestra- las tres pantallas
respondían que no había ningún abonado elegido aunque el operador estuviera
viendo uno.
"""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.payments.models import Charge
from apps.payments.tests.base import PaymentsTestCase


class OpeningTheFichaSelectsTheCustomerTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.user = self.make_user(
            "atc1", permissions=["view_charge", "view_payment", "view_receipt"]
        )

    def test_opening_the_ficha_records_the_selection(self):
        self.login(self.user)

        self.client.get(reverse("customers:detail", args=[self.customer.pk]))

        self.assertEqual(
            self.client.session["selected_customer_id"], self.customer.pk
        )

    def test_after_opening_the_ficha_the_debt_entry_opens_that_account(self):
        """El recorrido que fallaba: abrir una ficha y pulsar «Deuda»."""
        self.login(self.user)

        self.client.get(reverse("customers:detail", args=[self.customer.pk]))
        response = self.client.get(reverse("payments:selected_debt"))

        self.assertRedirects(
            response, reverse("payments:debt", args=[self.customer.pk])
        )

    def test_the_debt_screen_then_shows_that_customer_charges(self):
        Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo de prueba",
            amount=Decimal("80.00"),
            due_date=timezone.localdate() + timedelta(days=5),
        )

        self.login(self.user)
        self.client.get(reverse("customers:detail", args=[self.customer.pk]))
        response = self.client.get(reverse("payments:selected_debt"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["customer"], self.customer)
        self.assertContains(response, "Cargo de prueba")

    def test_the_history_and_receipts_entries_follow_the_same_selection(self):
        self.login(self.user)
        self.client.get(reverse("customers:detail", args=[self.customer.pk]))

        self.assertRedirects(
            self.client.get(reverse("payments:selected_history")),
            reverse("payments:history", args=[self.customer.pk]),
        )
        self.assertRedirects(
            self.client.get(reverse("payments:selected_receipts")),
            reverse("payments:receipts", args=[self.customer.pk]),
        )

    def test_opening_another_ficha_moves_the_selection(self):
        from apps.customers.models import Customer

        other = Customer.objects.create(
            code="CLI002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="10101010",
            first_name="Ana",
            paternal_surname="Lopez",
        )

        self.login(self.user)
        self.client.get(reverse("customers:detail", args=[self.customer.pk]))
        self.client.get(reverse("customers:detail", args=[other.pk]))

        self.assertRedirects(
            self.client.get(reverse("payments:selected_debt")),
            reverse("payments:debt", args=[other.pk]),
        )


class NoSelectionFallsBackToTheListTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.user = self.make_user("atc1", permissions=["view_charge"])

    def test_without_any_ficha_opened_it_shows_the_customer_list(self):
        """Sin abonado elegido se cae al padrón, que es donde se elige uno."""
        self.login(self.user)

        response = self.client.get(reverse("payments:selected_debt"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "customers/search.html")
        self.assertIn(self.customer, response.context["customers"])

    def test_the_notice_is_consumed_by_the_list_and_does_not_pile_up(self):
        """El aviso se ve una vez y no queda esperando otra pantalla.

        Antes solo algunas plantillas pintaban los avisos: el emitido al caer
        en el buscador no se consumía ahí y se acumulaba en la sesión, hasta
        salir en bloque al abrir una ficha. Seis clics dejaban seis banners.
        """
        self.login(self.user)

        for _ in range(3):
            self.client.get(reverse("payments:selected_debt"), follow=True)

        response = self.client.get(reverse("payments:selected_debt"), follow=True)

        self.assertEqual(len(response.context["messages"]), 1)

    def test_the_notice_is_rendered_as_a_dismissible_alert(self):
        self.login(self.user)

        response = self.client.get(reverse("payments:selected_debt"), follow=True)

        self.assertContains(response, "alert-dismissible")
        self.assertContains(response, "Abra la ficha de un abonado")

    def test_a_selection_of_a_deleted_customer_falls_back_too(self):
        self.login(self.user)

        session = self.client.session
        session["selected_customer_id"] = self.customer.pk + 999
        session.save()

        response = self.client.get(reverse("payments:selected_debt"), follow=True)

        self.assertTemplateUsed(response, "customers/search.html")


class NoticesAreRenderedOnceTests(PaymentsTestCase):
    """El shell pinta los avisos; las pantallas ya no los repiten."""

    def test_a_notice_appears_a_single_time_on_the_ficha(self):
        user = self.make_user("atc1", permissions=["view_charge"])
        self.login(user)

        # Cae en el buscador con un aviso y desde ahi abre una ficha, que era
        # la pantalla donde antes salian todos los avisos apilados.
        self.client.get(reverse("payments:selected_debt"))
        response = self.client.get(
            reverse("customers:detail", args=[self.customer.pk])
        )

        self.assertEqual(
            response.content.decode().count("Abra la ficha de un abonado"), 1
        )
