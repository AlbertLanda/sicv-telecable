
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

from apps.customers.models import Customer
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
            andes.sequence.issuer.business_name, "CABLE LOS ANDES S.A.C."
        )
        self.assertEqual(
            inversiones.sequence.issuer.business_name,
            "INVERSIONES EN TELECOMUNICACIONES DIGITALES S.A.C.",
        )
        self.assertNotEqual(
            andes.sequence.issuer.ruc, inversiones.sequence.issuer.ruc
        )

    def test_the_three_s010_books_are_three_companies(self):
        """«S010» nombra tres blocks de tres razones sociales distintas.

        Se sembraron los tres bajo SPEEDY QUANTICO, que era lo que se sabía
        entonces. VELOCIDAD DE LOS ANDES y RED OPTICA son empresas aparte con
        su propio RUC, así que el recibo de un block salía con el RUC de otra.
        """
        empresas = {
            sequence.code: sequence.issuer.ruc
            for sequence in ReceiptSequence.objects.filter(series="S010")
        }

        self.assertEqual(
            empresas,
            {
                "S010-VELOCIDAD": "20609510103",
                "S010-RED-OPTICA": "20610540369",
                "S010-SPEEDY": "20610526455",
            },
        )

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
            series="F001",
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
            series="F001",
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

    def test_the_companies_of_the_group_are_seeded(self):
        """Las cinco que emiten. ECO NET no entra: no tiene talonario, y una
        emisora sin talonario no llega a imprimirse en ningún sitio."""
        self.assertEqual(
            set(Issuer.objects.values_list("code", flat=True)),
            {"CLA", "INV", "SPQ", "VEL", "ROP"},
        )

    def test_no_company_keeps_a_placeholder_ruc(self):
        """El RUC de relleno se imprimía tal cual en la boleta y la factura."""
        for empresa in Issuer.objects.all():
            with self.subTest(empresa=empresa.code):
                self.assertFalse(empresa.ruc.startswith("2000000000"))

    def test_a_company_reads_as_its_business_name(self):
        """Es lo que sale impreso: nombrarla por su código en la pantalla
        obligaría a traducir mentalmente entre las dos formas."""
        empresa = Issuer.objects.get(code="SPQ")

        self.assertEqual(str(empresa), "SPEEDY QUANTICO E.I.R.L.")


class LaBoletaVaEnTiqueTests(PaymentsTestCase):
    """Los blocks de boleta numerados se entregan en un rollo estrecho.

    Son dos papeles distintos y el sistema tiene que saber cuál toca. Lo dice
    el talonario (`print_format`) y no la letra de la serie: los blocks de un
    cobrador también son boletas y **no** van en tique, así que una regla
    deducida de «empieza por B» los mandaría al papel equivocado.
    """

    # 80 mm de rollo, en puntos.
    ANCHO_TIQUE = 80 * mm

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

    def papel(self, series, number=None):
        """El ancho y el alto de la página, en puntos.

        `number` solo hace falta para los blocks que no numeran solos: los de
        un cobrador vienen numerados de papel y el cobro los exige.
        """
        _, receipt = register_payment(
            customer=self.customer,
            amount=Decimal("79.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.charge, Decimal("79.00"))],
            series=series,
            number=number,
        )

        buffer = BytesIO()
        pdf.render_receipt(receipt, buffer)

        medidas = re.search(
            rb"/MediaBox\s*\[([^\]]+)\]", buffer.getvalue()
        )

        self.assertIsNotNone(medidas, f"{series}: el PDF no declara su página")

        bordes = [float(valor) for valor in medidas.group(1).split()]

        return bordes[2] - bordes[0], bordes[3] - bordes[1]

    def test_a_boleta_book_prints_on_the_narrow_roll(self):
        ancho, alto = self.papel("B001")

        self.assertAlmostEqual(ancho, self.ANCHO_TIQUE, places=1)
        self.assertGreater(alto, ancho, "el tique se entrega en vertical")

    def test_an_invoice_book_keeps_the_half_sheet(self):
        """La factura no cambia: sigue en la media hoja apaisada."""
        ancho, alto = self.papel("F001")

        self.assertAlmostEqual(ancho, pdf.PAGE_SIZE[0], places=1)
        self.assertGreater(ancho, alto, "la media hoja va apaisada")

    def test_a_public_service_receipt_keeps_the_half_sheet(self):
        ancho, alto = self.papel("VCOND")

        self.assertAlmostEqual(ancho, pdf.PAGE_SIZE[0], places=1)

    def test_a_collector_book_keeps_the_half_sheet(self):
        """Es boleta y aun así no va en tique.

        Es el caso que obliga a guardar el formato en el talonario: por la
        serie -«B: JU1»- y por el título del documento, este block es una
        boleta como B001, y sin embargo se entrega en el otro papel.
        """
        sequence = ReceiptSequence.objects.get(code="JU1")

        self.assertEqual(sequence.document_title, "BOLETA DE VENTA ELECTRÓNICA")
        self.assertEqual(
            sequence.print_format, ReceiptSequence.PrintFormat.SHEET
        )

        ancho, _ = self.papel("JU1", number=120)

        self.assertAlmostEqual(ancho, pdf.PAGE_SIZE[0], places=1)

    def test_every_numbered_boleta_book_prints_on_the_roll(self):
        """Los diez blocks B00x del padrón, ninguno olvidado."""
        boletas = ReceiptSequence.objects.filter(
            series__startswith="B0",
            autonumber=True,
        )

        self.assertEqual(boletas.count(), 10)

        for sequence in boletas:
            with self.subTest(talonario=sequence.code):
                self.assertEqual(
                    sequence.print_format,
                    ReceiptSequence.PrintFormat.TICKET,
                )

    def test_the_ticket_carries_what_the_paper_declares(self):
        """El tique dice lo mismo que la media hoja, en otro sitio."""
        _, receipt = register_payment(
            customer=self.customer,
            amount=Decimal("79.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.charge, Decimal("79.00"))],
            series="B001",
        )

        buffer = BytesIO()
        pdf.render_receipt(receipt, buffer)
        crudo = buffer.getvalue()

        # Se busca en el PDF entero y no en el texto extraído: comprimido, el
        # contenido es binario, y lo que se comprueba es que el dato llegó al
        # archivo, no dónde quedó dibujado.
        original = pdf.SimpleDocTemplate

        with patch.object(
            pdf, "SimpleDocTemplate", partial(original, pageCompression=0)
        ):
            buffer = BytesIO()
            pdf.render_receipt(receipt, buffer)
            crudo = buffer.getvalue()

        for dato in (
            b"BOLETA DE VENTA",
            b"EMISI",
            b"ABONADO",
            b"MONEDA",
            b"DESCRIPCI",
            b"OP. GRAVADA",
            b"I.G.V.",
            b"CONDICI",
            b"sunat.gob.pe",
        ):
            with self.subTest(dato=dato):
                self.assertIn(dato, crudo)

    def test_the_ticket_grows_with_the_detail(self):
        """Un tique es tan largo como lo que tiene que decir.

        Con alto fijo, un cobro de una línea dejaba media cuarta de rollo en
        blanco y uno de diez se cortaba.
        """
        corto = self.papel("B001")[1]

        for mes in range(6):
            cargo = Charge.objects.create(
                customer=self.customer,
                concept=Charge.Concept.OTHER,
                description=f"ANEXO {mes}",
                amount=Decimal("20.00"),
                due_date=date(2026, 8, 31),
            )
            register_payment(
                customer=self.customer,
                amount=Decimal("20.00"),
                method=Payment.Method.CASH,
                branch=self.branch,
                user=self.cashier,
                allocations=[(cargo, Decimal("20.00"))],
                series="B002",
            )

        cargos = [
            Charge.objects.create(
                customer=self.customer,
                concept=Charge.Concept.OTHER,
                description=f"MENSUALIDAD {mes}",
                amount=Decimal("30.00"),
                due_date=date(2026, 9, 30),
            )
            for mes in range(6)
        ]
        _, largo = register_payment(
            customer=self.customer,
            amount=Decimal("180.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(cargo, Decimal("30.00")) for cargo in cargos],
            series="B002",
        )

        buffer = BytesIO()
        pdf.render_receipt(largo, buffer)
        bordes = [
            float(valor)
            for valor in re.search(
                rb"/MediaBox\s*\[([^\]]+)\]", buffer.getvalue()
            ).group(1).split()
        ]

        self.assertGreater(bordes[3] - bordes[1], corto)


class LosDatosDelEmisorTests(PaymentsTestCase):
    """INVERSIONES ya no imprime un RUC de relleno."""

    def test_inversiones_carries_its_real_identity(self):
        issuer = Issuer.objects.get(code="INV")

        self.assertEqual(
            issuer.business_name,
            "INVERSIONES EN TELECOMUNICACIONES DIGITALES S.A.C.",
        )
        self.assertEqual(issuer.ruc, "20603110456")

    def test_the_two_addresses_are_two_lines(self):
        """Son dos renglones de la cabecera del papel, no dos domicilios.

        Por eso viven en un campo separados por salto de línea: el sistema no
        tiene que distinguirlos, solo imprimirlos uno debajo de otro.
        """
        issuer = Issuer.objects.get(code="INV")
        renglones = issuer.address.splitlines()

        self.assertEqual(len(renglones), 2)
        self.assertIn("Jauja", renglones[0])
        self.assertIn("La Oroya", renglones[1])


class ElLogotipoSeDibujaSinSuMargenTests(PaymentsTestCase):
    """El archivo del logotipo trae aire dentro, y ese aire estorba.

    El que hay hoy en MEDIA_ROOT lleva un 13% de blanco arriba y un 19% abajo.
    Colocado alineado con la parte superior de su celda, lo que se ve arranca
    tres milímetros por debajo de la razón social que tiene al lado, y el
    logotipo parece caído en los dos papeles.

    Se recorta al dibujar y no en el archivo: el logotipo lo deja alguien en su
    sitio, no viene con el código.
    """

    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="ANEXO",
            amount=Decimal("50.00"),
            due_date=date(2026, 9, 30),
        )

    def dibujo_con_marco(self, carpeta, margen):
        """Un logotipo de 100x100 con `margen` píxeles de blanco alrededor."""
        from PIL import Image as PilImage, ImageDraw

        lienzo = PilImage.new("RGB", (100, 100), (255, 255, 255))
        pincel = ImageDraw.Draw(lienzo)
        pincel.rectangle(
            [margen, margen, 99 - margen, 99 - margen], fill=(10, 60, 120)
        )

        destino = Path(carpeta) / f"{pdf.LOGO_STEM}.png"
        lienzo.save(destino)

        return destino

    def test_the_white_margin_is_cropped_away(self):
        with TemporaryDirectory() as carpeta:
            archivo = self.dibujo_con_marco(carpeta, margen=20)

            recortado = pdf._sin_margen_blanco(archivo)

            from PIL import Image as PilImage

            self.assertEqual(PilImage.open(recortado).size, (60, 60))

    def test_a_drawing_without_margin_is_left_alone(self):
        """Sin aire que quitar, el recorte no se inventa ninguno."""
        with TemporaryDirectory() as carpeta:
            archivo = self.dibujo_con_marco(carpeta, margen=0)

            recortado = pdf._sin_margen_blanco(archivo)

            from PIL import Image as PilImage

            self.assertEqual(PilImage.open(recortado).size, (100, 100))

    def test_an_all_white_drawing_is_not_cropped_to_nothing(self):
        """Recortar un dibujo en blanco lo dejaría en nada."""
        from PIL import Image as PilImage

        with TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / f"{pdf.LOGO_STEM}.png"
            PilImage.new("RGB", (40, 40), (255, 255, 255)).save(archivo)

            self.assertEqual(pdf._sin_margen_blanco(archivo), str(archivo))

    def test_both_papers_print_without_any_logo(self):
        """Sin el archivo, la ventanilla entrega el papel igual.

        El tique preguntaba `is not None` y `_logo` devuelve cadena vacía, así
        que la cadena pasaba el guardia y el papel reventaba al pedirle
        alineación a un texto. Un despliegue al que no le han dejado el dibujo
        tiene que poder cobrar.
        """
        for series in ("B001", "F001"):
            with self.subTest(talonario=series):
                _, receipt = register_payment(
                    customer=self.customer,
                    amount=Decimal("10.00"),
                    method=Payment.Method.CASH,
                    branch=self.branch,
                    user=self.cashier,
                    allocations=[],
                    series=series,
                )

                with patch.object(pdf, "find_logo", lambda: None):
                    buffer = BytesIO()
                    pdf.render_receipt(receipt, buffer)

                self.assertGreater(len(buffer.getvalue()), 0)


class ElCodigoQrTests(PaymentsTestCase):
    """El QR, contra el de un comprobante declarado de verdad.

    El patrón no es una lectura de la norma: es el QR de la boleta
    B003-0034430 de INVERSIONES, aceptada por SUNAT, escaneado del papel:

        20603110456|03|B003|0034430|9.15|60.00|2025-12-22|1|20723004|R5Betfw/…

    Lo que se fija aquí es esa forma. El contenido todavía no lo respalda una
    declaración -el último campo es un resumen nuestro, no el hash de un XML
    firmado-, pero el día que lo sea, solo ese campo cambia.
    """

    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            amount=Decimal("60.00"),
            due_date=date(2026, 9, 30),
        )

    def cobrar(self, series="B001"):
        return register_payment(
            customer=self.customer,
            amount=Decimal("60.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.charge, Decimal("60.00"))],
            series=series,
        )[1]

    def contenido(self, receipt):
        """Lo que se codifica, sin dibujar el PDF."""
        widget = pdf._qr(receipt, receipt_totals(receipt), 30 * mm).contents[0]

        return widget.value

    def test_it_carries_ten_pipe_separated_fields(self):
        campos = self.contenido(self.cobrar()).split("|")

        self.assertEqual(len(campos), 10)

    def test_the_document_type_is_the_catalogue_code_not_its_name(self):
        """Iba «BOLETA DE VENTA ELECTRÓNICA» donde el comprobante real lleva
        «03». El QR no se lee con los ojos: un nombre ahí no lo entiende
        nadie."""
        campos = self.contenido(self.cobrar("B001")).split("|")

        self.assertEqual(campos[1], "03")

    def test_a_factura_declares_itself_as_one(self):
        campos = self.contenido(self.cobrar("F001")).split("|")

        self.assertEqual(campos[1], "01")

    def test_the_receiver_document_is_the_catalogue_code_too(self):
        """El sistema guarda «DNI», que es lo que el operador lee; el QR pide
        «1»."""
        campos = self.contenido(self.cobrar()).split("|")

        self.assertEqual(campos[7], "1")
        self.assertEqual(campos[8], self.customer.document_number)

    def test_a_company_is_identified_by_its_ruc_code(self):
        self.customer.document_type = Customer.DocumentType.RUC
        self.customer.document_number = "20123456789"
        self.customer.save(update_fields=["document_type", "document_number"])

        campos = self.contenido(self.cobrar("F001")).split("|")

        self.assertEqual(campos[7], "6")

    def test_the_number_keeps_its_leading_zeros(self):
        """El comprobante real lleva `0034430`, no `34430`."""
        campos = self.contenido(self.cobrar()).split("|")

        self.assertEqual(len(campos[3]), 7)
        self.assertTrue(campos[3].startswith("0"))

    def test_the_issue_date_goes_the_way_sunat_writes_it(self):
        """`2025-12-22` en el comprobante real, no `22/12/2025`."""
        receipt = self.cobrar()

        campos = self.contenido(receipt).split("|")

        self.assertEqual(campos[6], receipt.issued_at.strftime("%Y-%m-%d"))
        self.assertRegex(campos[6], r"^\d{4}-\d{2}-\d{2}$")

    def test_the_last_field_is_the_same_summary_that_is_printed(self):
        """En el comprobante real, el décimo campo y la línea «Resumen:» de
        debajo del QR dicen lo mismo. Si se separaran, el papel se estaría
        contradiciendo a sí mismo."""
        receipt = self.cobrar()
        totals = receipt_totals(receipt)

        campos = self.contenido(receipt).split("|")

        self.assertEqual(campos[9], pdf._resumen(receipt, totals))

    def test_the_amounts_are_the_ones_in_the_box(self):
        receipt = self.cobrar()
        totals = receipt_totals(receipt)

        campos = self.contenido(receipt).split("|")

        self.assertEqual(campos[4], f"{totals['igv']:.2f}")
        self.assertEqual(campos[5], f"{totals['total']:.2f}")

    def test_the_issuer_ruc_opens_the_code(self):
        receipt = self.cobrar()

        campos = self.contenido(receipt).split("|")

        self.assertEqual(campos[0], receipt.sequence.issuer.ruc)


class LaFacturaTraeLoSuyoTests(PaymentsTestCase):
    """Lo que la factura lleva y el recibo y la boleta no.

    Reproduce la F002-0005029 de INVERSIONES: condición de pago, guía de
    remisión, detracción, total neto, el cuadro de cuotas y la leyenda que
    invita a verificar en SUNAT. El resto de la hoja es el mismo dibujo.
    """

    # El importe de la F002-0005029 que se reproduce.
    IMPORTE = Decimal("494.30")

    def cobrar(self, series="F001", settled=True, due_date=None):
        """Un cobro con su propia deuda: dos llamadas no se pisan el saldo."""
        charge = Charge.objects.create(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            amount=self.IMPORTE,
            due_date=date(2026, 7, 31),
        )

        return register_payment(
            customer=self.customer,
            amount=self.IMPORTE,
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(charge, self.IMPORTE)],
            series=series,
            settled=settled,
            due_date=due_date,
        )[1]

    def texto(self, pieza):
        """Todo el texto de una tabla armada, sin dibujar el PDF."""
        trozos = []

        def recorrer(cosa):
            if hasattr(cosa, "_cellvalues"):
                for fila in cosa._cellvalues:
                    for celda in fila:
                        recorrer(celda)
            elif isinstance(cosa, (list, tuple)):
                for item in cosa:
                    recorrer(item)
            elif hasattr(cosa, "text"):
                trozos.append(cosa.text)
            elif isinstance(cosa, str):
                trozos.append(cosa)

        recorrer(pieza)

        return "\n".join(trozos)

    def cabecera_de(self, receipt):
        return self.texto(_estilos_y(receipt, pdf._abonado))

    def test_a_factura_announces_its_payment_condition(self):
        receipt = self.cobrar()

        self.assertIn("Condición de pago", self.cabecera_de(receipt))
        self.assertIn("CONTADO", self.cabecera_de(receipt))

    def test_a_factura_emitted_pending_is_on_credit(self):
        """Emitido «Cancelado: No» es dinero que no entró y que vence: eso es
        crédito, y no hace falta un campo aparte que lo diga."""
        receipt = self.cobrar(settled=False, due_date=date(2026, 7, 31))

        self.assertIn("CREDITO", self.cabecera_de(receipt))

    def test_a_factura_keeps_the_dispatch_note_row_even_if_empty(self):
        """El sistema no emite guías. La fila va igual: sin ella, dos facturas
        de la misma empresa no tendrían la misma forma."""
        self.assertIn("G. Remisión", self.cabecera_de(self.cobrar()))

    def test_a_receipt_carries_neither_of_those_rows(self):
        """En el recibo no están en blanco: no están."""
        cabecera = self.cabecera_de(self.cobrar("S010-SPEEDY"))

        self.assertNotIn("Condición de pago", cabecera)
        self.assertNotIn("G. Remisión", cabecera)

    def pie_de(self, receipt):
        totals = receipt_totals(receipt)

        return self.texto(pdf._pie(receipt, pdf._estilos(), 194 * mm, totals))

    def test_the_factura_box_adds_detraction_and_net_total(self):
        pie = self.pie_de(self.cobrar())

        self.assertIn("Detracción", pie)
        self.assertIn("Total Neto", pie)

    def test_the_receipt_box_keeps_its_seven_rows(self):
        pie = self.pie_de(self.cobrar("S010-SPEEDY"))

        self.assertNotIn("Detracción", pie)
        self.assertNotIn("Total Neto", pie)

    def test_only_the_factura_invites_to_verify_at_sunat(self):
        self.assertIn("www.sunat.gob.pe", pdf._leyenda(self.cobrar()))
        self.assertNotIn(
            "www.sunat.gob.pe", pdf._leyenda(self.cobrar("S010-SPEEDY"))
        )

    def cuotas_de(self, receipt):
        totals = receipt_totals(receipt)

        return pdf._cuotas(receipt, pdf._estilos(), 194 * mm, totals)

    def test_a_credit_factura_shows_its_instalment(self):
        receipt = self.cobrar(settled=False, due_date=date(2026, 7, 31))

        cuotas = self.texto(self.cuotas_de(receipt))

        self.assertIn("Total de cuotas: 1", cuotas)
        self.assertIn("Monto neto pendiente de pago: S/494.30", cuotas)
        self.assertIn("31/07/2026", cuotas)
        self.assertIn("494.30", cuotas)

    def test_a_cash_factura_has_no_instalment_box(self):
        """Al contado no hay nada que vencer, y el papel original no lo
        dibuja."""
        self.assertIsNone(self.cuotas_de(self.cobrar()))

    def test_a_receipt_never_has_the_instalment_box(self):
        receipt = self.cobrar(
            "S010-SPEEDY", settled=False, due_date=date(2026, 7, 31)
        )

        self.assertIsNone(self.cuotas_de(receipt))

    def test_the_pending_amount_does_not_move_when_it_is_paid(self):
        """El papel dice lo que se debía al emitirlo. Si cambiara al pagarse,
        dos copias del mismo comprobante dirían cifras distintas."""
        receipt = self.cobrar(settled=False, due_date=date(2026, 7, 31))
        antes = self.texto(self.cuotas_de(receipt))

        receipt.payment.confirm()

        self.assertEqual(self.texto(self.cuotas_de(receipt)), antes)

    def test_the_credit_factura_still_fits_on_one_sheet(self):
        """El cuadro de cuotas cuelga del pie. Si no entrara en el hueco que
        reparte el detalle, empujaría el pie a una segunda hoja."""
        receipt = self.cobrar(settled=False, due_date=date(2026, 7, 31))
        buffer = BytesIO()

        render_receipt(receipt, buffer)

        self.assertEqual(buffer.getvalue().count(b"/Type /Page\n"), 1)


def _estilos_y(receipt, pieza):
    """La pieza del dibujo, armada con los estilos y el ancho de la hoja."""
    return pieza(receipt, pdf._estilos(), 194 * mm)
