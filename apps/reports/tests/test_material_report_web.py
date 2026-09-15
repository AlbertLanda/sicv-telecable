"""La pantalla del reporte y sus cuatro salidas.

Las pruebas de formato no comprueban cómo se ve el papel -eso no se puede
afirmar desde aquí-, sino lo que sí puede fallar en silencio: que el archivo
salga del formato que dice ser y que lleve dentro las filas consultadas. Un
`.xlsx` que en realidad es una tabla HTML renombrada pasa por bueno hasta que
alguien intenta abrirlo, y entonces ya está en manos de logística.
"""

from django.urls import reverse

from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY

from .pdf_text import pdf_strings, pdf_text
from .test_material_report import MaterialReportTestCase


class MaterialReportAccessTests(MaterialReportTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("reports:materials")

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_user_without_permission_is_rejected(self):
        self.client.force_login(self.technician)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_operator_with_permission_sees_the_form(self):
        self.client.force_login(self.operator)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reporte de materiales")
        self.assertContains(response, "Desde")
        self.assertContains(response, "Hasta")
        self.assertContains(response, "Exportar")

    def test_the_form_offers_every_scope_of_the_legacy_system(self):
        self.client.force_login(self.operator)

        response = self.client.get(self.url)

        for etiqueta in (
            "Todo",
            "Cable - Instalaciones",
            "Cable - Anexos",
            "Cable - Reconexiones",
            "Cable - Cortes",
            "Cable - Servicios",
            "Cable - Averías",
        ):
            self.assertContains(response, etiqueta)

    def test_the_button_exports_and_points_at_the_sheet(self):
        """«Exportar» y no «Imprimir»: tres de los cuatro formatos bajan un
        archivo, y solo uno llega a una impresora."""
        self.client.force_login(self.operator)

        response = self.client.get(self.url)

        self.assertContains(response, "Exportar")
        self.assertContains(response, reverse("reports:materials_list"))

    def test_html_and_pdf_open_in_a_new_tab(self):
        """Los dos que el navegador pinta. Sobre la pantalla actual taparían
        el formulario, y volver a consultar obligaría a retroceder."""
        from apps.reports.forms import VIEWED_FORMATS

        self.assertEqual(set(VIEWED_FORMATS), {"HTML", "PDF"})

        self.client.force_login(self.operator)
        response = self.client.get(self.url)

        for formato in VIEWED_FORMATS:
            with self.subTest(formato=formato):
                self.assertContains(response, f'"{formato}"')

    def test_word_and_excel_stay_on_the_same_page(self):
        """Se descargan: una pestaña nueva quedaría en blanco detrás."""
        from apps.reports.forms import VIEWED_FORMATS

        self.assertNotIn("WORD", VIEWED_FORMATS)
        self.assertNotIn("EXCEL", VIEWED_FORMATS)

    def test_the_form_travels_by_get_so_the_sheet_has_a_shareable_url(self):
        """La hoja se abre en otra pestaña: su periodo tiene que caber en la
        barra de direcciones para poder pegarse y recargarse."""
        self.client.force_login(self.operator)

        response = self.client.get(self.url)

        self.assertContains(response, 'method="get"')

    def test_the_form_offers_every_format(self):
        self.client.force_login(self.operator)

        response = self.client.get(self.url)

        for etiqueta in ("PDF", "Word", "Excel", "Html"):
            self.assertContains(response, etiqueta)


class MaterialReportRenderTests(MaterialReportTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("reports:materials_list")
        self.client.force_login(self.operator)

        sesion = self.client.session
        sesion[ACTIVE_BRANCH_SESSION_KEY] = self.branch.pk
        sesion.save()

        self.order = self.make_order(self.make_customer("CLI001"))
        self.add_material(self.order, self.utp, "45.50")

    def imprimir(self, **extra):
        datos = {
            "date_from": self.today.isoformat(),
            "date_to": self.today.isoformat(),
            "scope": "ALL",
            "export_format": "HTML",
        }
        datos.update(extra)

        return self.client.get(self.url, datos)

    def cuerpo(self, response):
        return b"".join(response.streaming_content)

    # --- HTML ------------------------------------------------------------

    def test_html_paints_the_sheet_with_its_rows(self):
        response = self.imprimir()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Registro de materiales")
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, "Cable UTP")
        # «45,50»: el idioma del sistema es español y la coma es su separador
        # decimal, igual que en el resto de las pantallas del SICV.
        self.assertContains(response, "45,50")
        self.assertContains(response, "Total: 1")

    def test_the_sheet_names_its_own_browser_tab(self):
        """Se abren varias a la vez al comparar periodos; sin fecha en el
        título, las pestañas son indistinguibles."""
        response = self.imprimir()

        self.assertContains(
            response,
            f"<title>Registro de materiales - {self.today.strftime('%d/%m/%Y')}</title>",
            html=False,
        )

    def test_the_same_url_can_be_reloaded(self):
        """Lo que un GET compra: recargar no pregunta por reenvíos."""
        primera = self.imprimir()
        segunda = self.imprimir()

        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 200)
        self.assertContains(segunda, self.order.order_number)

    def test_html_prints_the_active_branch_in_the_header(self):
        response = self.imprimir()

        self.assertContains(response, "Huancayo")

    def test_the_sheet_is_a_document_without_the_system_shell(self):
        """Se abre en una pestaña aparte: es un papel, no una pantalla.

        El menú lateral y la barra superior robarían el ancho que necesitan
        las trece columnas, y no tienen nada que hacer sobre algo que se va a
        imprimir o a guardar en PDF.
        """
        response = self.imprimir()

        self.assertContains(response, self.order.order_number)
        self.assertNotContains(response, "sicv-sidebar")
        self.assertNotContains(response, "Buscar opción...")

    def test_html_says_so_when_there_was_no_movement(self):
        response = self.imprimir(scope="CUT")

        self.assertContains(response, "No se registraron movimientos")
        self.assertContains(response, "Total: 0")

    def test_an_inverted_period_goes_back_to_the_form_with_its_message(self):
        response = self.imprimir(
            date_from=self.today.isoformat(),
            date_to="2020-01-01",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no puede ser posterior")
        self.assertNotContains(response, "Registro de materiales")

    def test_the_report_never_shows_another_branch(self):
        ajena = self.make_order(
            self.make_customer("CLI002", branch=self.other_branch),
            branch=self.other_branch,
        )
        self.add_material(ajena)

        response = self.imprimir()

        self.assertContains(response, self.order.order_number)
        self.assertNotContains(response, ajena.order_number)
        self.assertContains(response, "Total: 1")

    # --- Archivos --------------------------------------------------------

    def test_pdf_is_a_real_pdf(self):
        response = self.imprimir(export_format="PDF")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(self.cuerpo(response).startswith(b"%PDF"))

    def test_pdf_is_a4_landscape(self):
        """Trece columnas en vertical se parten en cuatro líneas cada una."""
        cuerpo = self.cuerpo(self.imprimir(export_format="PDF"))

        self.assertIn(b"/MediaBox [ 0 0 841.8898 595.2756 ]", cuerpo)

    def test_pdf_carries_the_rows_it_was_asked_for(self):
        texto = pdf_text(self.cuerpo(self.imprimir(export_format="PDF")))

        self.assertIn("Registro de materiales", texto)
        self.assertIn("Huancayo", texto)
        self.assertIn(self.order.order_number, texto)
        self.assertIn("Cable UTP", texto)
        self.assertIn("Total: 1", texto)

    def test_the_pdf_header_is_a_single_line(self):
        """Hora, título y sede, y nada debajo: la misma franja que la hoja en
        pantalla, el Excel y el Word."""
        cadenas = pdf_strings(self.cuerpo(self.imprimir(export_format="PDF")))

        self.assertEqual(cadenas[1], "Registro de materiales")
        self.assertEqual(cadenas[2], "Huancayo")

        # Lo siguiente que se dibuja ya es la tabla. Si alguien devuelve un
        # subtítulo entre el título y la cabecera, esto lo caza.
        self.assertEqual(cadenas[3], "Orden")

    def test_the_pdf_prints_the_thirteen_column_labels(self):
        from apps.reports.materials import COLUMNS

        cadenas = pdf_strings(self.cuerpo(self.imprimir(export_format="PDF")))

        for columna in COLUMNS:
            with self.subTest(columna=columna["label"]):
                self.assertIn(columna["label"], cadenas)

    def test_excel_is_a_real_xlsx_with_the_rows_inside(self):
        from io import BytesIO

        from openpyxl import load_workbook

        response = self.imprimir(export_format="EXCEL")

        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])

        libro = load_workbook(BytesIO(self.cuerpo(response)))
        hoja = libro.active
        texto = [
            str(celda.value)
            for fila in hoja.iter_rows()
            for celda in fila
            if celda.value is not None
        ]

        self.assertIn("Registro de materiales", texto)
        self.assertIn(self.order.order_number, texto)
        self.assertIn("Cable UTP", texto)
        self.assertIn("Total: 1", texto)

    def test_excel_keeps_the_quantity_as_a_number(self):
        """Logística suma la columna en la propia hoja; un texto no se suma."""
        from io import BytesIO

        from openpyxl import load_workbook

        response = self.imprimir(export_format="EXCEL")
        hoja = load_workbook(BytesIO(self.cuerpo(response))).active

        cantidades = [
            celda.value
            for fila in hoja.iter_rows()
            for celda in fila
            if isinstance(celda.value, float)
        ]

        self.assertIn(45.5, cantidades)

    def test_word_is_a_real_docx_with_the_rows_inside(self):
        from io import BytesIO

        from docx import Document

        response = self.imprimir(export_format="WORD")

        self.assertEqual(response.status_code, 200)
        self.assertIn("wordprocessingml", response["Content-Type"])

        documento = Document(BytesIO(self.cuerpo(response)))
        texto = [p.text for p in documento.paragraphs]
        celdas = [
            celda.text
            for tabla in documento.tables
            for fila in tabla.rows
            for celda in fila.cells
        ]

        # La franja va en un solo párrafo, con la hora, el título y la sede
        # separados por tabulaciones: es la misma cabecera de una línea que la
        # pantalla y el Excel.
        franja = texto[0]

        self.assertIn("Registro de materiales", franja)
        self.assertIn("Huancayo", franja)
        self.assertEqual(franja.count("	"), 2)

        self.assertIn("Total: 1", texto)
        self.assertIn(self.order.order_number, celdas)
        self.assertIn("Cable UTP", celdas)

    def test_the_quantity_reads_the_same_on_screen_and_on_paper(self):
        """El reporte es un documento con cuatro entregas, no cuatro cifras."""
        from io import BytesIO

        from docx import Document

        documento = Document(
            BytesIO(self.cuerpo(self.imprimir(export_format="WORD")))
        )
        celdas = [
            celda.text
            for tabla in documento.tables
            for fila in tabla.rows
            for celda in fila.cells
        ]

        self.assertIn("45,50 Metro", celdas)
        self.assertContains(self.imprimir(), "45,50")

    def test_the_word_header_reads_like_the_other_formats(self):
        """Cabecera azul y letra blanca: era el único de los cuatro donde la
        cabecera se confundía con la primera fila de datos."""
        from io import BytesIO

        from docx import Document

        documento = Document(
            BytesIO(self.cuerpo(self.imprimir(export_format="WORD")))
        )
        cabecera = documento.tables[0].rows[0]

        for celda in cabecera.cells:
            with self.subTest(celda=celda.text):
                self.assertIn("0F4C7F", celda._tc.xml)

        primera = cabecera.cells[0].paragraphs[0].runs[0]

        self.assertTrue(primera.bold)
        self.assertEqual(str(primera.font.color.rgb), "FFFFFF")

    def test_every_viewed_format_is_really_served_inline(self):
        """La lista dice qué abre pestaña; esto comprueba que el servidor lo
        cumple. Un formato declarado «se ve» pero servido como adjunto
        abriría una pestaña que solo descarga y se queda en blanco."""
        from apps.reports.forms import VIEWED_FORMATS

        for formato in VIEWED_FORMATS:
            if formato == "HTML":
                continue

            with self.subTest(formato=formato):
                response = self.imprimir(export_format=formato)
                self.assertIn("inline", response["Content-Disposition"])

    def test_every_file_format_carries_the_period_in_its_name(self):
        for formato in ("PDF", "EXCEL", "WORD"):
            with self.subTest(formato=formato):
                response = self.imprimir(export_format=formato)

                self.assertIn(
                    self.today.strftime("%Y%m%d"),
                    response["Content-Disposition"],
                )

    def test_the_thirteen_columns_are_the_same_in_every_format(self):
        """Una columna añadida a una salida y olvidada en otra es el fallo
        que la lista única de columnas existe para impedir."""
        from io import BytesIO

        from docx import Document
        from openpyxl import load_workbook

        from apps.reports.materials import COLUMNS

        etiquetas = [columna["label"] for columna in COLUMNS]

        hoja = load_workbook(
            BytesIO(self.cuerpo(self.imprimir(export_format="EXCEL")))
        ).active
        # Fila 3: la franja de identificación ocupa una sola línea y deja la
        # cuarta para respirar antes de la tabla.
        cabecera_excel = [
            celda.value for celda in hoja[3] if celda.value is not None
        ]

        documento = Document(
            BytesIO(self.cuerpo(self.imprimir(export_format="WORD")))
        )
        cabecera_word = [celda.text for celda in documento.tables[0].rows[0].cells]

        self.assertEqual(cabecera_excel, etiquetas)
        self.assertEqual(cabecera_word, etiquetas)

        html = self.imprimir()
        for etiqueta in etiquetas:
            self.assertContains(html, etiqueta)


class MaterialReportSidebarTests(MaterialReportTestCase):
    def test_the_menu_offers_materials_to_whoever_can_see_them(self):
        self.client.force_login(self.operator)

        response = self.client.get(reverse("reports:materials"))

        self.assertContains(response, reverse("reports:materials"))
        self.assertContains(response, "Materiales")
