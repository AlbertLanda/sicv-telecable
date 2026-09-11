"""
Las pantallas de cobranza usan el mismo sistema visual que la ficha del cliente.

Lo que se fija aquí es que no vuelvan a bifurcarse. El sistema `tc-*` vivía
dentro de la ficha del cliente, así que cobranza nació con una maqueta propia
de Bootstrap crudo y las dos pantallas se veían de aplicaciones distintas.
Ahora el CSS está en un parcial compartido y la identidad del abonado la pinta
un solo bloque: si alguien lo copia en lugar de incluirlo, estas pruebas lo
notan.
"""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.payments.models import Charge, Payment
from apps.payments.services import register_payment
from apps.payments.tests.base import PaymentsTestCase


DESIGN_PARTIAL = "_tc_design.html"
CUSTOMER_HERO = "customers/_hero.html"


class SharedDesignTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo de prueba",
            amount=Decimal("50.00"),
            due_date=timezone.localdate() + timedelta(days=10),
        )

        self.user = self.make_user(
            "operador1",
            permissions=[
                "view_charge",
                "add_charge",
                "view_payment",
                "view_receipt",
                "add_payment",
                "grant_paymentcommitment",
            ],
        )
        self.login(self.user)

    def account_screens(self):
        return [
            reverse("payments:debt", args=[self.customer.pk]),
            reverse("payments:history", args=[self.customer.pk]),
            reverse("payments:receipts", args=[self.customer.pk]),
            reverse("payments:charge_create", args=[self.customer.pk]),
            reverse("payments:register", args=[self.customer.pk]),
            reverse("payments:commitment_create", args=[self.customer.pk]),
        ]

    def test_every_screen_loads_the_shared_design(self):
        """Ninguna pantalla trae su propio CSS.

        Copiarlo en cada plantilla las separa al primer ajuste: una quedaría
        con el trazo viejo sin que nadie lo note.
        """
        for url in self.account_screens():
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, DESIGN_PARTIAL)

    def test_every_account_screen_describes_the_customer_with_the_same_block(self):
        """La identidad del abonado la pinta el bloque de la ficha.

        Si cada pantalla lo describiera por su cuenta, podrían acabar diciendo
        cosas distintas sobre quién es y qué tiene activo.
        """
        for url in self.account_screens():
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertTemplateUsed(response, CUSTOMER_HERO)

    def test_the_customer_ficha_loads_the_same_design(self):
        """La ficha dejó de llevar el CSS embebido y lo incluye igual."""
        response = self.client.get(
            reverse("customers:detail", args=[self.customer.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, DESIGN_PARTIAL)

    def test_the_three_tabs_are_offered_on_every_account_screen(self):
        """Las tres vistas de la cuenta se alcanzan entre sí.

        Son la misma cuenta desde ángulos distintos: obligar a volver al
        buscador para cambiar de una a otra es lo que hacía el sistema que se
        está reemplazando.
        """
        tabs = [
            reverse("payments:debt", args=[self.customer.pk]),
            reverse("payments:history", args=[self.customer.pk]),
            reverse("payments:receipts", args=[self.customer.pk]),
        ]

        for url in self.account_screens():
            with self.subTest(url=url):
                response = self.client.get(url)

                for tab in tabs:
                    self.assertContains(response, tab)

    def test_the_receipt_loads_the_shared_design(self):
        _, receipt = register_payment(
            customer=self.customer,
            amount=Decimal("50.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.charge, Decimal("50.00"))],
        )

        response = self.client.get(
            reverse("payments:receipt_detail", args=[receipt.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, DESIGN_PARTIAL)

    def test_no_account_screen_repeats_the_debt_as_a_metric_strip(self):
        """Ninguna pantalla encabeza la cuenta con la tira de cifras.

        Estuvo sobre la tabla de deudas y se retiró: decía lo mismo que la
        tabla que va debajo, y empujaba las deudas por debajo del pliegue.
        La deuda se sigue calculando para la vista -la tabla y sus botones
        viven de ella-, pero no se pinta como resumen.
        """
        for url in self.account_screens():
            for figure in ("Deuda al", "Deudas abiertas", "Vencimiento más antiguo"):
                with self.subTest(url=url, figure=figure):
                    response = self.client.get(url)

                    self.assertNotContains(response, figure)

    def test_the_debt_screen_still_computes_the_debt(self):
        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertEqual(response.context["debt"]["total"], Decimal("50.00"))


class NoTemplateSyntaxLeaksTests(PaymentsTestCase):
    """Ninguna pantalla imprime sintaxis de plantilla como si fuera texto.

    `{# ... #}` es un comentario de una sola línea. Escrito en varias, Django
    no lo reconoce y lo pinta tal cual; en un formulario de rejilla ese texto
    ocupa además la primera celda y corre todas las etiquetas un sitio, así
    que cada campo acaba junto a la etiqueta del anterior. Se vio en pantalla
    antes que en las pruebas, que es justo lo que esta clase evita.
    """

    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo de prueba",
            amount=Decimal("50.00"),
            due_date=timezone.localdate() + timedelta(days=10),
        )

        self.login(
            self.make_user(
                "operador2",
                permissions=[
                    "view_charge",
                    "add_charge",
                    "view_payment",
                    "view_receipt",
                    "add_payment",
                    "grant_paymentcommitment",
                ],
            )
        )

    def screens(self):
        return [
            reverse("customers:detail", args=[self.customer.pk]),
            reverse("customers:orders", args=[self.customer.pk]),
            reverse("customers:activity", args=[self.customer.pk]),
            reverse("payments:debt", args=[self.customer.pk]),
            reverse("payments:history", args=[self.customer.pk]),
            reverse("payments:receipts", args=[self.customer.pk]),
            reverse("payments:charge_create", args=[self.customer.pk]),
            reverse("payments:register", args=[self.customer.pk]),
            reverse("payments:commitment_create", args=[self.customer.pk]),
        ]

    def test_no_screen_prints_template_syntax(self):
        for url in self.screens():
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()

                self.assertNotIn("{#", body)
                self.assertNotIn("#}", body)
                self.assertNotIn("{%", body)
                self.assertNotIn("{{", body)
