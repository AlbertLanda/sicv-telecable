"""
El papel: qué dice el comprobante que se entrega al abonado.

Dos cosas se fijan aquí. La primera, que quién emite lo decide el talonario:
el block de CABLE LOS ANDES imprime esa razón social con su RUC, y el de
SPEEDY QUANTICO la suya, sin que la pantalla tenga que preguntar nada aparte
del talonario que ya elige para el correlativo.

La segunda, la aritmética que el papel declara. El sistema guarda el dinero
con el IGV dentro -la mensualidad de S/ 79 es S/ 79- y el comprobante tiene
que abrirlo. Las cifras de estas pruebas salen de un comprobante real del
sistema que se reemplaza, para que el papel nuevo diga lo mismo que el viejo.
"""

import re
from datetime import date
from decimal import Decimal
from functools import partial
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from reportlab.lib.units import mm

from django.urls import reverse

from apps.payments import pdf

from apps.payments.invoicing import (
    amount_in_words,
    receipt_lines,
    receipt_totals,
)
from apps.payments.models import Charge, Issuer, Payment, ReceiptSequence
from apps.payments.pdf import render_receipt
from apps.payments.services import register_payment
from apps.payments.tests.base import PaymentsTestCase


class ImporteEnLetrasTests(PaymentsTestCase):
    """«SON: CIENTO CUATRO Y 00/100 SOLES»."""

    def test_it_writes_the_amounts_of_the_window(self):
        casos = [
            ("104.00", "CIENTO CUATRO Y 00/100 SOLES"),
            ("79.00", "SETENTA Y NUEVE Y 00/100 SOLES"),
            ("100.00", "CIEN Y 00/100 SOLES"),
            ("21.50", "VEINTIUNO Y 50/100 SOLES"),
            ("1000.00", "MIL Y 00/100 SOLES"),
            ("2345.67", "DOS MIL TRESCIENTOS CUARENTA Y CINCO Y 67/100 SOLES"),
            ("0.50", "CERO Y 50/100 SOLES"),
        ]

        for cifra, letras in casos:
            with self.subTest(cifra=cifra):
                self.assertEqual(amount_in_words(Decimal(cifra)), letras)

    def test_the_cents_go_in_figures_over_a_hundred(self):
        """Deletrearlos alargaría la línea sin hacerla más segura."""
        self.assertTrue(
            amount_in_words(Decimal("15.86")).endswith("Y 86/100 SOLES")
        )


class DesgloseDelPapelTests(PaymentsTestCase):
    """Lo que declara el recuadro de importes.

    El escenario es el de un comprobante real: tres conceptos de S/ 5, S/ 30 y
    S/ 79 con el IGV dentro, dos de ellos con pronto pago de S/ 5.
    """

    def setUp(self):
        super().setUp()

        self.cargos = []

        for importe, descuento in (
            (Decimal("5.00"), Decimal("0.00")),
            (Decimal("30.00"), Decimal("5.00")),
            (Decimal("79.00"), Decimal("5.00")),
        ):
            cargo = Charge.objects.create(
                customer=self.customer,
                concept=Charge.Concept.MONTHLY,
                description="PLAN DUO PREMIUM 800MG",
                period=date(2026, 8, 16),
                period_end=date(2026, 9, 15),
                amount=importe,
                due_date=date(2026, 9, 15),
                early_discount=descuento,
                discount_deadline=date(2026, 9, 10) if descuento else None,
            )
            self.cargos.append(cargo)

        self.payment, self.receipt = register_payment(
            customer=self.customer,
            amount=Decimal("104.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[
                (self.cargos[0], Decimal("5.00")),
                (self.cargos[1], Decimal("25.00")),
                (self.cargos[2], Decimal("74.00")),
            ],
            day=date(2026, 9, 1),
            series="B001",
        )

    def test_the_unit_price_comes_without_the_tax(self):
        """S/ 79 con IGV dentro son 66.949153 de precio unitario.

        Seis decimales y no dos: con dos, el total no se puede reconstruir
        desde el precio y la fila deja de poder comprobarse.
        """
        lineas = receipt_lines(self.receipt)
        unitarios = [linea["unit_price"] for linea in lineas]

        self.assertIn(Decimal("4.237288"), unitarios)
        self.assertIn(Decimal("25.423729"), unitarios)
        self.assertIn(Decimal("66.949153"), unitarios)

    def test_each_line_adds_up_by_itself(self):
        """Precio redondeado menos descuento es exactamente el total.

        Es lo que el abonado comprueba con la calculadora del teléfono cuando
        reclama, y un céntimo que no cuadra convierte la comprobación en una
        discusión.
        """
        for linea in receipt_lines(self.receipt):
            with self.subTest(descripcion=linea["description"]):
                self.assertEqual(
                    linea["unit_price"].quantize(Decimal("0.01"))
                    - linea["discount"],
                    linea["total"],
                )

    def test_the_box_says_what_the_old_paper_said(self):
        """Las siete cifras del comprobante que se reemplaza."""
        totales = receipt_totals(self.receipt)

        self.assertEqual(totales["gravada"], Decimal("88.14"))
        self.assertEqual(totales["discount"], Decimal("8.47"))
        self.assertEqual(totales["igv"], Decimal("15.86"))
        self.assertEqual(totales["total"], Decimal("104.00"))
        self.assertEqual(totales["exonerada"], Decimal("0.00"))
        self.assertEqual(totales["inafecta"], Decimal("0.00"))
        self.assertEqual(totales["gratuita"], Decimal("0.00"))

    def test_base_and_tax_add_up_to_the_money_received(self):
        """El importe total no se calcula: es el dinero que entró.

        Calculando el IGV aparte y sumando, un céntimo de redondeo dejaba el
        papel diciendo S/ 103.99 donde el cajero había recibido S/ 104.00.
        """
        totales = receipt_totals(self.receipt)

        self.assertEqual(
            totales["gravada"] + totales["igv"], totales["total"]
        )

    def test_the_columns_add_up_to_the_box(self):
        lineas = receipt_lines(self.receipt)
        totales = receipt_totals(self.receipt, lineas)

        self.assertEqual(
            sum(linea["total"] for linea in lineas), totales["gravada"]
        )
        self.assertEqual(
            sum(linea["discount"] for linea in lineas), totales["discount"]
        )

    def test_the_description_carries_the_code_and_the_period(self):
        """«COD JA01-... PLAN DUO PREMIUM 800MG PERIODO 16/08 - 15/09».

        El papel viaja solo: quien lo recibe en la oficina no tiene la
        pantalla al lado para saber de qué abonado y de qué mes es.
        """
        descripciones = [
            linea["description"] for linea in receipt_lines(self.receipt)
        ]

        for descripcion in descripciones:
            with self.subTest(descripcion=descripcion):
                self.assertIn(f"COD {self.customer.code}", descripcion)
                self.assertIn("PERIODO 16/08/2026 - 15/09/2026", descripcion)


class LaRazonSocialLaDecideElTalonarioTests(PaymentsTestCase):
    """Cada block imprime la empresa a la que pertenece."""

    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="ANEXO",
            amount=Decimal("50.00"),
            due_date=date(2026, 9, 30),
        )

    def cobrar(self, series):
        return register_payment(
            customer=self.customer,
            amount=Decimal("50.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[],
            series=series,
        )[1]

    def test_the_seeded_books_all_have_an_issuer(self):
        """Ninguno se queda sin cabecera al imprimir."""
        sin_empresa = ReceiptSequence.objects.filter(issuer__isnull=True)

        self.assertFalse(
            sin_empresa.exists(),
            f"Talonarios sin empresa: {list(sin_empresa.values_list('code', flat=True))}",
        )

    def test_two_books_of_different_companies_print_different_names(self):
        """Es la razón de que la empresa cuelgue del talonario y no de la sede.

        La misma ventanilla cobra para las dos, así que colgarla del lugar de
        cobro haría imprimir la misma razón social en los dos papeles.
        """
        andes = self.cobrar("B001")
        inversiones = self.cobrar("B002")

        self.assertEqual(
            andes.sequence.issuer.business_name, "CABLE LOS ANDES E.I.R.L."
        )
        self.assertEqual(
            inversiones.sequence.issuer.business_name, "INVERSIONES E.I.R.L."
        )
        self.assertNotEqual(
            andes.sequence.issuer.ruc, inversiones.sequence.issuer.ruc
        )

    def test_the_three_s010_books_share_the_company(self):
        """«S010» nombra tres blocks distintos de la misma empresa."""
        empresas = {
            sequence.issuer.business_name
            for sequence in ReceiptSequence.objects.filter(series="S010")
        }

        self.assertEqual(empresas, {"SPEEDY QUANTICO E.I.R.L."})

    def test_the_title_belongs_to_the_book_not_the_company(self):
        """La misma razón social emite boletas, facturas y recibos."""
        titulos = {
            code: ReceiptSequence.objects.get(code=code).document_title
            for code in ("B001", "F001", "VCOND")
        }

        self.assertEqual(titulos["B001"], "BOLETA DE VENTA ELECTRÓNICA")
        self.assertEqual(titulos["F001"], "FACTURA ELECTRÓNICA")
        self.assertEqual(
            titulos["VCOND"], "RECIBO DE SERVICIO PÚBLICO ELECTRÓNICO"
        )


class ElPapelSeDibujaTests(PaymentsTestCase):
    """Que el PDF salga, y que salga aunque falte algo."""

    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.MONTHLY,
            description="INTERNET 300MG",
            period=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            amount=Decimal("79.00"),
            due_date=date(2026, 8, 31),
        )

        self.payment, self.receipt = register_payment(
            customer=self.customer,
            amount=Decimal("79.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.charge, Decimal("79.00"))],
            series="B001",
        )

    def dibujar(self, receipt=None):
        buffer = BytesIO()
        nombre = render_receipt(receipt or self.receipt, buffer)

        return nombre, buffer.getvalue()

    def test_it_draws_the_receipt(self):
        nombre, contenido = self.dibujar()

        self.assertEqual(nombre, f"{self.receipt.full_number}.pdf")
        self.assertTrue(contenido.startswith(b"%PDF-"))
        self.assertGreater(len(contenido), 2000)

    def test_a_book_without_a_company_still_prints(self):
        """Un despliegue a medio configurar no deja la ventanilla parada.

        Sin esto, un talonario nuevo sin empresa asignada reventaba al
        imprimir y el abonado se quedaba sin su papel.
        """
        self.receipt.sequence.issuer = None
        self.receipt.sequence.save()

        _, contenido = self.dibujar()

        self.assertTrue(contenido.startswith(b"%PDF-"))

    def test_a_customer_without_an_address_still_prints(self):
        # Se le quita la marca de principal en vez de borrarla: la direccion
        # esta protegida por la suscripcion que cuelga de ella, que es como
        # se comporta en produccion.
        self.customer.addresses.update(is_primary=False)

        _, contenido = self.dibujar()

        self.assertTrue(contenido.startswith(b"%PDF-"))

    def test_a_voided_receipt_prints_differently(self):
        """El papel de un cobro anulado no puede parecerse al de uno válido."""
        _, valido = self.dibujar()

        self.payment.void(user=self.cashier, reason="Cobro duplicado.")
        self.receipt.refresh_from_db()
        _, anulado = self.dibujar()

        self.assertTrue(anulado.startswith(b"%PDF-"))
        self.assertNotEqual(len(valido), len(anulado))

    def test_the_screen_downloads_it(self):
        viewer = self.make_user(
            "consulta11",
            permissions=["view_charge", "view_payment", "view_receipt"],
        )
        self.login(viewer)

        response = self.client.get(
            reverse("payments:receipt_pdf", args=[self.receipt.pk])
        )
        contenido = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(contenido.startswith(b"%PDF-"))


class ElLogotipoTests(PaymentsTestCase):
    """Que se encuentre el archivo, se llame como se llame.

    Es el camino que falla callado: sin logotipo el papel sale igual -a
    proposito, para que la ventanilla no se pare-, asi que mirar el PDF no
    distingue «falta la imagen» de «esta mal puesta».
    """

    def test_it_is_not_found_when_there_is_nothing(self):
        with TemporaryDirectory() as carpeta:
            with patch.object(pdf, "LOGO_DIR", Path(carpeta)):
                self.assertIsNone(pdf.find_logo())

    def test_any_of_the_accepted_extensions_works(self):
        """Guardado como .jpg tambien lo coge.

        Exigir exactamente .png dejaba el papel sin logo por una extension,
        sin avisar a nadie.
        """
        for extension in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            with self.subTest(extension=extension):
                with TemporaryDirectory() as carpeta:
                    ruta = Path(carpeta) / f"{pdf.LOGO_STEM}{extension}"
                    ruta.write_bytes(b"no importa el contenido aqui")

                    with patch.object(pdf, "LOGO_DIR", Path(carpeta)):
                        self.assertEqual(pdf.find_logo(), ruta)

    def test_what_the_browser_sticks_on_the_name_does_not_break_it(self):
        """«telecable-logo.jpg.jpeg» es lo que salio de la descarga real.

        Con el nombre exacto exigido, el papel salia sin logo por una
        extension de mas y sin decirlo en ninguna parte.
        """
        for nombre in (
            "telecable-logo.jpg.jpeg",
            "telecable-logo (1).png",
            "telecable-logo-final.png",
        ):
            with self.subTest(nombre=nombre):
                with TemporaryDirectory() as carpeta:
                    ruta = Path(carpeta) / nombre
                    ruta.write_bytes(b"x")

                    with patch.object(pdf, "LOGO_DIR", Path(carpeta)):
                        self.assertEqual(pdf.find_logo(), ruta)

    def test_the_png_wins_when_there_are_two(self):
        with TemporaryDirectory() as carpeta:
            png = Path(carpeta) / f"{pdf.LOGO_STEM}.png"
            jpg = Path(carpeta) / f"{pdf.LOGO_STEM}.jpg"
            png.write_bytes(b"x")
            jpg.write_bytes(b"x")

            with patch.object(pdf, "LOGO_DIR", Path(carpeta)):
                self.assertEqual(pdf.find_logo(), png)

    def test_the_clean_name_wins_over_the_duplicate(self):
        """Entre el que alguien puso y el que dejo caer una segunda descarga."""
        with TemporaryDirectory() as carpeta:
            limpio = Path(carpeta) / f"{pdf.LOGO_STEM}.png"
            copia = Path(carpeta) / f"{pdf.LOGO_STEM} (1).png"
            limpio.write_bytes(b"x")
            copia.write_bytes(b"x")

            with patch.object(pdf, "LOGO_DIR", Path(carpeta)):
                self.assertEqual(pdf.find_logo(), limpio)

    def test_a_broken_image_does_not_stop_the_receipt(self):
        """Una descarga a medias no puede dejar a la ventanilla sin papel."""
        with TemporaryDirectory() as carpeta:
            roto = Path(carpeta) / f"{pdf.LOGO_STEM}.png"
            roto.write_bytes(b"esto no es un PNG")

            with patch.object(pdf, "LOGO_DIR", Path(carpeta)):
                self.assertEqual(pdf._logo(10), "")


class ElPapelLlenaLaHojaTests(PaymentsTestCase):
    """La caja del detalle se estira hasta el pie.

    Sin esto el comprobante ocupaba cuatro quintos de la hoja y dejaba el
    resto en blanco, que es lo que distingue un comprobante de un borrador. Y
    un cobro de una linea y otro de cinco salian con siluetas distintas.
    """

    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.MONTHLY,
            description="INTERNET 300MG",
            period=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            amount=Decimal("79.00"),
            due_date=date(2026, 8, 31),
        )
        _, self.receipt = register_payment(
            customer=self.customer,
            amount=Decimal("79.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.charge, Decimal("79.00"))],
            series="B001",
        )

    def medir(self):
        """Cuanto ocupa el contenido y cuanto cabe, en puntos."""
        from reportlab.platypus import SimpleDocTemplate

        from apps.payments.invoicing import receipt_lines, receipt_totals

        estilos = pdf._estilos()
        lineas = receipt_lines(self.receipt)
        totales = receipt_totals(self.receipt, lineas)

        margen = 8 * mm
        ancho = pdf.PAGE_SIZE[0] - 2 * margen
        doc = SimpleDocTemplate(
            BytesIO(),
            pagesize=pdf.PAGE_SIZE,
            leftMargin=margen,
            rightMargin=margen,
            topMargin=margen,
            bottomMargin=margen,
        )

        piezas = [
            pdf._cabecera(self.receipt, estilos, ancho),
            pdf._abonado(self.receipt, estilos, ancho),
            pdf._detalle(self.receipt, estilos, ancho, lineas),
            pdf._pie(self.receipt, estilos, ancho, totales),
        ]
        separadores = 9.5 * mm
        sin_estirar = sum(
            pieza.wrap(ancho, doc.height)[1] for pieza in piezas
        ) + separadores
        disponible = doc.height - 2 * pdf.FRAME_PADDING

        return sin_estirar, disponible, ancho, doc, estilos, lineas, totales

    def test_the_detail_box_takes_what_is_left_over(self):
        sin_estirar, disponible, ancho, doc, estilos, lineas, totales = self.medir()
        sobra = disponible - sin_estirar

        self.assertGreater(
            sobra, 0, "No sobra hueco que repartir: el caso no prueba nada."
        )

        estirado = pdf._detalle(
            self.receipt, estilos, ancho, lineas,
            pdf.RELLENO_MINIMO + sobra,
        )
        crecimiento = (
            estirado.wrap(ancho, doc.height)[1]
            - pdf._detalle(self.receipt, estilos, ancho, lineas).wrap(
                ancho, doc.height
            )[1]
        )

        # Se lleva el hueco entero, no una parte.
        self.assertAlmostEqual(crecimiento, sobra, delta=1)

    def test_one_line_fits_in_a_single_page(self):
        buffer = BytesIO()
        pdf.render_receipt(self.receipt, buffer)

        self.assertEqual(
            re.findall(b"/Count" + bytes([32]) + b"+(" + b"[0-9]+)", buffer.getvalue()),
            [b"1"],
        )

    def test_the_type_is_big_enough_to_read_across_a_counter(self):
        """Los cuerpos van en proporcion al papel, no al minimo legible.

        Este comprobante se lee a un brazo de distancia sobre un mostrador, a
        veces con el abonado mirandolo del otro lado.
        """
        estilos = pdf._estilos()

        self.assertGreaterEqual(estilos["empresa"].fontSize, 14)
        self.assertGreaterEqual(estilos["ruc"].fontSize, 11)

        for nombre in ("etiqueta", "dato", "th", "celda", "num", "pie"):
            with self.subTest(estilo=nombre):
                self.assertGreaterEqual(estilos[nombre].fontSize, 7.5)


class LasCajasVanRedondeadasTests(PaymentsTestCase):
    """Las cuatro cajas del papel llevan la esquina redondeada.

    Se comprueba contando las curvas que el PDF dibuja, que es lo unico
    observable sin mirarlo: cuatro esquinas por caja y cuatro cajas -RUC,
    abonado, detalle e importes-. Asi, si alguien añade una caja y se olvida
    del radio, la cuenta lo dice.
    """

    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.MONTHLY,
            description="INTERNET 300MG",
            amount=Decimal("79.00"),
            due_date=date(2026, 8, 31),
        )
        _, self.receipt = register_payment(
            customer=self.customer,
            amount=Decimal("79.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.charge, Decimal("79.00"))],
            series="B001",
        )

    def curvas(self):
        """Cuántos operadores Bézier dibuja el comprobante.

        Se apaga la compresion del PDF para poder leerlos: comprimido, el
        contenido es binario y no hay forma de contar nada.
        """
        original = pdf.SimpleDocTemplate

        with patch.object(
            pdf,
            "SimpleDocTemplate",
            partial(original, pageCompression=0),
        ):
            buffer = BytesIO()
            pdf.render_receipt(self.receipt, buffer)

            # El salto se construye con su codigo y no escrito: pasando
            # por el shell, la barra invertida se perdia y el literal
            # acababa partido en dos lineas.
            salto = bytes([10])

            return len(re.findall(b" c" + salto, buffer.getvalue()))

    def test_the_four_boxes_have_rounded_corners(self):
        self.assertEqual(self.curvas(), 16)

    def test_without_the_radius_there_are_no_curves(self):
        """Que las 16 son del redondeo y no de otra cosa del dibujo."""
        with patch.object(pdf, "ESQUINAS", ("ROUNDEDCORNERS", [0, 0, 0, 0])):
            self.assertEqual(self.curvas(), 0)

    def test_the_radius_stays_subtle(self):
        """Un radio grande acerca el papel a una tarjeta de pantalla.

        Este documento se lee junto a otros en papel y tiene que seguir
        pareciendo un comprobante.
        """
        self.assertLessEqual(pdf.RADIO, 3 * mm)
        self.assertGreater(pdf.RADIO, 0)


class EmpresaEmisoraTests(PaymentsTestCase):
    """El modelo de la razón social."""

    def test_the_three_companies_of_the_group_are_seeded(self):
        self.assertEqual(
            set(Issuer.objects.values_list("code", flat=True)),
            {"CLA", "INV", "SPQ"},
        )

    def test_a_company_reads_as_its_business_name(self):
        """Es lo que sale impreso: nombrarla por su código en la pantalla
        obligaría a traducir mentalmente entre las dos formas."""
        empresa = Issuer.objects.get(code="SPQ")

        self.assertEqual(str(empresa), "SPEEDY QUANTICO E.I.R.L.")
