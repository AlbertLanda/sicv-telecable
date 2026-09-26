"""
El historial de pagos y la ventana del comprobante.

Las dos pantallas son la misma lista leída desde dos distancias: el historial
dice qué deudas quedaron cerradas y con qué documento, y el comprobante abre
uno de esos documentos con la ficha con la que se cobró, bloqueada.

Lo que se fija aquí es que las columnas del historial sean las de la deuda
-porque el operador salta de una pestaña a la otra-, que una fila sea una
deuda pagada y no un cobro, y que el comprobante no ofrezca ningún campo que
se pueda escribir.
"""

import re
from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.payments.models import Charge, Payment
from apps.payments.services import register_payment
from apps.payments.tests.base import PaymentsTestCase


class HistorialBase(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.octubre = Charge.objects.create(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            description="INTERNET 300MG",
            period=date(2025, 10, 1),
            period_end=date(2025, 10, 31),
            amount=Decimal("65.00"),
            due_date=date(2025, 10, 31),
        )
        self.noviembre = Charge.objects.create(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            description="INTERNET 300MG",
            period=date(2025, 11, 1),
            period_end=date(2025, 11, 30),
            amount=Decimal("65.00"),
            due_date=date(2025, 11, 30),
        )

        self.viewer = self.make_user(
            "consulta9",
            permissions=["view_charge", "view_payment", "view_receipt"],
        )

    def url(self):
        return reverse("payments:history", args=[self.customer.pk])


class ColumnasDelHistorialTests(HistorialBase):
    """Las columnas del tablero de deuda, más el comprobante."""

    def pay_october(self, **overrides):
        datos = dict(
            customer=self.customer,
            amount=Decimal("65.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.octubre, Decimal("65.00"))],
        )
        datos.update(overrides)

        return register_payment(**datos)

    def body(self):
        self.login(self.viewer)

        return self.client.get(self.url()).content.decode()

    def test_it_carries_the_columns_of_the_debt_board(self):
        """Las del tablero, en su orden, y el comprobante al final.

        El operador salta entre las dos pestañas comparando lo que se debe
        con lo que se pagó. Abonado, cantidad y moneda salieron como del
        tablero -siempre eran este cliente, 1 y soles-; el medio de pago va
        tras el periodo, y el comprobante se lee en dos: su serie y número,
        que abren la ficha, y el PDF.
        """
        self.pay_october()

        cabecera = self.body().split("<thead>")[1].split("</thead>")[0]
        columnas = [
            texto.strip()
            for texto in re.findall(r"<th[^>]*>(.*?)</th>", cabecera, re.S)
        ]

        self.assertEqual(
            columnas,
            [
                "Fecha", "Detalle", "Periodo", "Método", "Monto",
                "Vencimiento", "Estado", "Serie", "Comprobante",
            ],
        )

    def test_the_row_reads_like_the_board(self):
        """Nombre corto, periodo en letras y fechas como las del tablero."""
        self.pay_october()

        body = self.body()

        self.assertIn(">Internet 300MG</td>", body)
        self.assertIn('title="INTERNET 300MG"', body)
        self.assertIn(">Oct 2025</td>", body)
        self.assertIn(">31 Oct 2025</td>", body)

    def test_the_pdf_opens_the_receipt_as_it_was_handed_over(self):
        """En la pestaña de al lado y en el visor, no como descarga."""
        _, receipt = self.pay_october()
        pdf = reverse("payments:receipt_pdf", args=[receipt.pk])

        body = self.body()

        self.assertRegex(
            body,
            rf'href="{re.escape(pdf)}\?ver=1"\s+target="_blank"',
        )

    def test_the_method_is_the_one_registered(self):
        self.pay_october(method=Payment.Method.YAPE, reference="778899")

        body = self.body()

        self.assertIn('<i class="bi bi-phone" aria-hidden="true"></i>Yape', body)
        self.assertIn('title="Operación 778899"', body)

    def test_the_series_opens_how_the_collection_was_registered(self):
        """Serie y número como van impresos, hacia la ficha del cobro."""
        _, receipt = self.pay_october()
        ficha = reverse("payments:receipt_detail", args=[receipt.pk])

        self.assertRegex(
            self.body(),
            rf'href="{re.escape(ficha)}"[^>]*>{re.escape(receipt.full_number)}</a>',
        )

    def test_the_history_heads_without_the_blue_band(self):
        self.assertNotIn('class="tc-section-head banner"', self.body())

    def test_a_paid_row_says_so(self):
        self.pay_october()

        self.assertIn('class="status-success"', self.body())

    def test_a_voided_row_keeps_its_reason_on_the_status(self):
        """El motivo que llenaba «Observación», a un pase del cursor."""
        payment, _ = self.pay_october()
        payment.void(user=self.cashier, reason="Cobro duplicado.")

        body = self.body()

        self.assertIn('class="is-voided"', body)
        self.assertIn('title="Anulado: Cobro duplicado."', body)

    def test_a_pending_row_says_the_money_has_not_come_in(self):
        self.pay_october(settled=False)

        body = self.body()

        self.assertIn('class="status-warning"', body)
        self.assertIn("el dinero todavía no entra", body)


class UnaFilaPorDeudaPagadaTests(HistorialBase):
    """La fila es la deuda, no el cobro."""

    def test_a_payment_covering_two_months_shows_two_rows(self):
        """Cada mes con su periodo y su vencimiento.

        Agrupado por cobro, esa fila tendría dos periodos y dos vencimientos
        y no cabría en las columnas de la deuda.
        """
        register_payment(
            customer=self.customer,
            amount=Decimal("130.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[
                (self.octubre, Decimal("65.00")),
                (self.noviembre, Decimal("65.00")),
            ],
        )

        self.login(self.viewer)
        rows = self.client.get(self.url()).context["rows"]

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["charge"].pk for row in rows},
            {self.octubre.pk, self.noviembre.pk},
        )

    def test_an_advance_without_debt_still_shows_up(self):
        """Un pago a cuenta no tiene deuda que lo explique, pero existe.

        Listando solo las aplicaciones, el dinero que el abonado entregó por
        adelantado desaparecía del historial y nadie podía dar cuenta de él.
        """
        register_payment(
            customer=self.customer,
            amount=Decimal("40.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[],
        )

        self.login(self.viewer)
        rows = self.client.get(self.url()).context["rows"]

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["charge"])
        self.assertEqual(rows[0]["amount"], Decimal("40.00"))

    def test_the_amount_is_the_one_issued_not_the_one_discounted(self):
        """«Monto» quiere decir lo mismo aquí que en la deuda y en el cobro.

        El pronto pago cerró la mensualidad de 65 con 60. La columna sigue
        diciendo 65 -lo emitido- y el descuento se explica en el comprobante,
        que es donde el papel lo justifica.
        """
        self.octubre.early_discount = Decimal("5.00")
        self.octubre.discount_deadline = date(2025, 10, 10)
        self.octubre.save()

        register_payment(
            customer=self.customer,
            amount=Decimal("60.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.octubre, Decimal("60.00"))],
            day=date(2025, 10, 5),
        )

        self.login(self.viewer)
        rows = self.client.get(self.url()).context["rows"]

        self.assertEqual(rows[0]["amount"], Decimal("65.00"))


class DocumentoAbreElComprobanteTests(HistorialBase):
    """La columna «Documento» lleva a la ficha del cobro, bloqueada."""

    def setUp(self):
        super().setUp()

        self.octubre.early_discount = Decimal("5.00")
        self.octubre.discount_deadline = date(2025, 10, 10)
        self.octubre.save()

        self.payment, self.receipt = register_payment(
            customer=self.customer,
            amount=Decimal("60.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.octubre, Decimal("60.00"))],
            day=date(2025, 10, 5),
        )

    def receipt_url(self):
        return reverse("payments:receipt_detail", args=[self.receipt.pk])

    def test_the_history_links_the_document_to_its_receipt(self):
        """La serie lleva a la ficha y el PDF nombra el comprobante."""
        self.login(self.viewer)
        body = self.client.get(self.url()).content.decode()

        self.assertIn(self.receipt_url(), body)
        self.assertIn(f"el comprobante {self.receipt.full_number}", body)

    def test_the_receipt_shows_the_sheet_of_the_collection(self):
        """Las mismas etiquetas que la pantalla de cobro."""
        self.login(self.viewer)
        body = self.client.get(self.receipt_url()).content.decode()

        for etiqueta in (
            "Serie",
            "Número",
            "Usuario",
            "Deuda",
            "Total",
            "Cancelado",
            "Fecha de pago",
            "Hora de pago",
            "Medio de pago",
            "Número de operación",
            "Cobrador",
            "Fecha de vencimiento",
            "Anulado",
            "Observaciones",
        ):
            with self.subTest(etiqueta=etiqueta):
                self.assertIn(etiqueta, body)

    def ficha(self):
        """El trozo de la pagina que es la ficha, sin la barra de arriba.

        La barra trae sus propios campos -la busqueda, el selector de
        oficina- y contarlos aqui diria que la ficha tiene campos abiertos
        cuando los abiertos son los de la barra.
        """
        body = self.client.get(self.receipt_url()).content.decode()

        # Se ancla en el marcado y no en el nombre de la clase: «tc-sheet» y
        # «tc-card-footer» aparecen antes en la hoja de estilos, y buscar el
        # nombre a secas devolvia el CSS en vez de la ficha.
        inicio = body.index('<section class="tc-card tc-section tc-full tc-sheet">')
        fin = body.index('<div class="tc-card-footer', inicio)

        return body[inicio:fin]

    def test_every_field_of_the_sheet_is_blocked(self):
        """Un comprobante emitido no se corrige: se anula y se emite otro.

        Un solo campo escribible invitaría a corregirlo ahí, y lo escrito no
        llegaría a ninguna parte porque la pantalla no envía nada.
        """
        self.login(self.viewer)
        ficha = self.ficha()

        campos = ficha.count("<input") + ficha.count("<textarea")
        bloqueados = ficha.count("disabled")

        self.assertGreater(campos, 0)
        self.assertEqual(campos, bloqueados)

    def test_the_sheet_has_nothing_to_submit(self):
        """Sin formulario no hay nada que enviar ni boton que lo sugiera."""
        self.login(self.viewer)

        self.assertNotIn("<form", self.ficha())

    def test_it_shows_the_charges_that_were_covered(self):
        self.login(self.viewer)
        response = self.client.get(self.receipt_url())

        self.assertEqual(len(response.context["allocations"]), 1)
        self.assertEqual(
            response.context["totals"]["gross"], Decimal("65.00")
        )
        self.assertEqual(
            response.context["totals"]["net"], Decimal("60.00")
        )

    def test_the_number_keeps_its_leading_zeros(self):
        self.login(self.viewer)
        response = self.client.get(self.receipt_url())

        self.assertEqual(len(response.context["printed_number"]), 7)
        self.assertIn(
            response.context["printed_number"],
            response.content.decode(),
        )

    def test_without_permission_the_receipt_is_forbidden(self):
        self.login(self.make_user("sinpermiso9"))

        self.assertEqual(self.client.get(self.receipt_url()).status_code, 403)


class DescargarPdfTests(DocumentoAbreElComprobanteTests):
    """El mismo comprobante, como archivo."""

    def pdf_url(self):
        return reverse("payments:receipt_pdf", args=[self.receipt.pk])

    def test_the_screen_offers_the_two_actions(self):
        self.login(self.viewer)
        body = self.client.get(self.receipt_url()).content.decode()

        self.assertIn("Descargar PDF", body)
        self.assertIn("Imprimir", body)
        self.assertIn(self.pdf_url(), body)

    def test_printing_opens_the_pdf_in_the_next_tab(self):
        """Lo que se imprime es el papel, no la pantalla de consulta.

        Reabriendo esta pantalla se imprimia la ficha de consulta -etiquetas,
        campos bloqueados- en vez del comprobante que el abonado se lleva, y
        el dialogo saltaba encima de lo que el operador estaba mirando.
        """
        self.login(self.viewer)
        body = self.client.get(self.receipt_url()).content.decode()

        self.assertIn(f'{self.pdf_url()}?ver=1', body)
        self.assertIn('target="_blank"', body)
        self.assertNotIn("window.print()", body)

    def test_seeing_it_does_not_download_it(self):
        """`inline` para ver, `attachment` para guardar.

        Como adjunto, «Imprimir» dejaba un archivo en la carpeta de descargas
        cada vez que el operador solo queria mirarlo.
        """
        self.login(self.viewer)
        response = self.client.get(self.pdf_url() + "?ver=1")

        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertNotIn("attachment", response["Content-Disposition"])
        self.assertIn(
            f'filename="{self.receipt.full_number}.pdf"',
            response["Content-Disposition"],
        )

    def test_it_downloads_a_pdf_named_after_the_receipt(self):
        """El archivo se llama como el número que el operador lee en pantalla.

        Nombrarlo con el id interno dejaría una carpeta de descargas donde
        ningún archivo se puede relacionar con el papel que se entregó.
        """
        self.login(self.viewer)
        response = self.client.get(self.pdf_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(
            f'filename="{self.receipt.full_number}.pdf"',
            response["Content-Disposition"],
        )
        self.assertIn("attachment", response["Content-Disposition"])

    def test_the_file_is_a_readable_pdf(self):
        self.login(self.viewer)
        response = self.client.get(self.pdf_url())
        contenido = b"".join(response.streaming_content)

        self.assertTrue(contenido.startswith(b"%PDF-"))
        self.assertGreater(len(contenido), 1000)

    def test_a_voided_receipt_says_so_on_paper(self):
        """El papel de un cobro anulado no puede parecerse al de uno válido.

        Si el PDF sale igual, el abonado se queda con un comprobante que
        acredita un pago que ya no existe.
        """
        self.payment.void(user=self.cashier, reason="Cobro duplicado.")

        self.login(self.viewer)
        response = self.client.get(self.pdf_url())
        contenido = b"".join(response.streaming_content)

        self.assertTrue(contenido.startswith(b"%PDF-"))

        # El texto va comprimido dentro del PDF, asi que se comprueba en la
        # pantalla, que lee del mismo sitio.
        pantalla = self.client.get(self.receipt_url()).content.decode()
        self.assertIn("Comprobante anulado", pantalla)
        self.assertIn("Cobro duplicado.", pantalla)

    def test_without_permission_the_pdf_is_forbidden(self):
        """El archivo lleva los mismos datos que la pantalla.

        Sin el mismo control, bastaría con adivinar la URL del PDF para leer
        un comprobante que la pantalla niega.
        """
        self.login(self.make_user("sinpermiso10"))

        self.assertEqual(self.client.get(self.pdf_url()).status_code, 403)

    def test_an_advance_without_debt_also_prints(self):
        """Un pago a cuenta no tiene deuda, pero tiene papel."""
        _, receipt = register_payment(
            customer=self.customer,
            amount=Decimal("40.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[],
        )

        self.login(self.viewer)
        response = self.client.get(
            reverse("payments:receipt_pdf", args=[receipt.pk])
        )
        contenido = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(contenido.startswith(b"%PDF-"))
