"""
Las pantallas de cobranza usan el mismo sistema visual que la ficha del cliente.

Lo que se fija aquí es que no vuelvan a bifurcarse. El sistema `tc-*` vivía
dentro de la ficha del cliente, así que cobranza nació con una maqueta propia
de Bootstrap crudo y las dos pantallas se veían de aplicaciones distintas.
Ahora el CSS está en un parcial compartido y la identidad del abonado la pinta
un solo bloque: si alguien lo copia en lugar de incluirlo, estas pruebas lo
notan.
"""

import re
from datetime import timedelta
from pathlib import Path
from decimal import Decimal

from django.test import SimpleTestCase
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

    def account_tables(self):
        """Las tres pestañas que presentan una tabla larga del abonado."""
        return [
            reverse("payments:debt", args=[self.customer.pk]),
            reverse("payments:history", args=[self.customer.pk]),
            reverse("payments:receipts", args=[self.customer.pk]),
        ]

    def section_heads(self, body):
        return re.findall(
            r'<div class="tc-section-head[^"]*">.*?</div>',
            body,
            flags=re.DOTALL,
        )

    def test_every_account_table_heads_with_the_blue_band(self):
        """Las tres tablas de la cuenta encabezan igual.

        Comprobantes se quedó con la cabecera blanca cuando deuda e historial
        pasaron a la franja: puestas una al lado de otra, la que no la lleva
        parece de otra pantalla y no otra cara del mismo abonado.
        """
        for url in self.account_tables():
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()

                self.assertIn('class="tc-section-head banner"', body)

    def test_no_account_table_counts_its_rows_in_the_head(self):
        """El conteo lo da el pie del paginador y solo él.

        Comprobantes lo decía además en una píldora de la cabecera. Dos cifras
        del mismo dato a dos palmos una de otra se separan en cuanto una de
        las dos deje de contar lo mismo -y la del pie cuenta el total aunque
        la tabla muestre una página-.
        """
        for url in self.account_tables():
            body = self.client.get(url).content.decode()
            heads = self.section_heads(body)

            # Sin esto la prueba pasaria en vacio si la cabecera cambiara de
            # marcado y el patron dejara de encontrarla.
            self.assertTrue(heads, f"{url} no pinta ninguna cabecera de seccion")

            for head in heads:
                with self.subTest(url=url, head=head[:60]):
                    self.assertNotIn("tc-pill", head)

    def test_the_debt_screen_still_computes_the_debt(self):
        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertEqual(response.context["debt"]["total"], Decimal("50.00"))


class MargenLateralDeLaFichaTests(SimpleTestCase):
    """Una ficha tiene un solo margen lateral, y lo pone la variable.

    La franja azul de la cabecera, los campos del cuerpo y los botones del pie
    arrancan en la misma línea vertical porque los tres leen `--tc-pad-x`. Una
    ficha que quiera más aire redefine la variable sobre la tarjeta entera
    -eso hace `.tc-sheet`-, nunca el padding de una de las tres zonas: tocando
    solo el cuerpo, la tarjeta acababa con el título a 18px del borde, los
    campos a 26 y los botones a 18 otra vez.

    Se mira el CSS de las plantillas y no la página renderizada porque es una
    regla de hoja de estilos: el navegador la resuelve, el cliente de pruebas
    no.
    """

    ZONA = re.compile(
        r"\.tc-sheet \.(tc-section-head|tc-section-body|tc-card-footer)"
        r"[^{]*\{[^}]*?padding:\s*([^;}]+)"
    )

    VARIABLE = "var(--tc-pad-x)"

    def sheet_templates(self):
        """Las plantillas que maquetan una ficha."""
        raices = [Path("apps"), Path("templates")]
        encontradas = [
            archivo
            for raiz in raices
            for archivo in raiz.rglob("*.html")
            if ".tc-sheet " in archivo.read_text(encoding="utf-8")
        ]

        self.assertTrue(encontradas, "no se encontró ninguna ficha que revisar")

        return encontradas

    def horizontal(self, shorthand):
        """Los componentes laterales de un `padding` abreviado."""
        partes = shorthand.split()

        if len(partes) == 1:
            return partes
        if len(partes) == 4:
            return [partes[1], partes[3]]

        return [partes[1]]

    def test_no_sheet_sets_its_own_lateral_margin(self):
        for plantilla in self.sheet_templates():
            css = plantilla.read_text(encoding="utf-8")

            for zona, shorthand in self.ZONA.findall(css):
                for valor in self.horizontal(shorthand.strip()):
                    with self.subTest(plantilla=plantilla.name, zona=zona):
                        self.assertEqual(
                            valor,
                            self.VARIABLE,
                            f"{plantilla.name} fija el margen lateral de "
                            f".{zona} en «{valor}»; si las otras dos zonas de "
                            f"la tarjeta no lo fijan igual, las tres arrancan "
                            f"en lineas distintas",
                        )


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
