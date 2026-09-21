"""El contrato de abonado en papel, dibujado con ReportLab.

Reproduce el contrato vigente que ATC entregó como referencia: la cabecera
con la marca y el código del documento, el recuadro de las partes, las doce
cláusulas y el pie de firmas.

Se dibuja aquí y no en una plantilla HTML por la misma razón que el
comprobante de cobranza: lo que sale por la impresora tiene que ser el papel,
no una pantalla. Así el botón «Imprimir contrato» abre el PDF en el visor del
navegador, con sus botones de imprimir y guardar, sin pasar por una página
intermedia.

Aquí no vive ni una línea del contrato: el texto está en `clausulas.py`, que
es de donde leen los dos formatos en que se entrega -este y el Word-. Este
módulo solo decide cómo se ve cada bloque en el papel: tipografía, medidas,
la franja azul del recuadro y dónde puede partir una hoja.
"""

from functools import partial

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .clausulas import (
    bloques_del_contrato,
    datos_de_las_partes,
    titulo_del_contrato,
)
from .document import datos_del_contrato


PAGE_SIZE = A4

MARGEN_LATERAL = 15 * mm
MARGEN_SUPERIOR = 26 * mm
MARGEN_INFERIOR = 22 * mm

AZUL = colors.HexColor("#0F4C7F")
AZUL_CLARO = colors.HexColor("#B9C9D9")
GRIS = colors.HexColor("#333333")


def _estilos():
    """Tipografía con serifas, como el documento que se reemplaza."""

    cuerpo = ParagraphStyle(
        "cuerpo",
        fontName="Times-Roman",
        fontSize=9,
        leading=11.6,
        alignment=TA_JUSTIFY,
        spaceAfter=3.2 * mm,
        textColor=GRIS,
    )

    return {
        "cuerpo": cuerpo,
        "titulo": ParagraphStyle(
            "titulo",
            parent=cuerpo,
            fontName="Times-Bold",
            fontSize=12,
            leading=15,
            alignment=TA_CENTER,
            textColor=AZUL,
            spaceAfter=1 * mm,
        ),
        "subtitulo": ParagraphStyle(
            "subtitulo",
            parent=cuerpo,
            fontName="Times-Bold",
            fontSize=8.5,
            alignment=TA_CENTER,
            textColor=AZUL,
            spaceAfter=5 * mm,
        ),
        "clausula": ParagraphStyle(
            "clausula",
            parent=cuerpo,
            fontName="Times-Bold",
            fontSize=9.5,
            leading=12,
            alignment=0,
            textColor=AZUL,
            spaceBefore=3.5 * mm,
            spaceAfter=1.6 * mm,
        ),
        "recuadro": ParagraphStyle(
            "recuadro",
            parent=cuerpo,
            fontSize=8.5,
            leading=11,
            alignment=0,
            spaceAfter=1.4 * mm,
        ),
        "recuadro_cabecera": ParagraphStyle(
            "recuadro_cabecera",
            parent=cuerpo,
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9.5,
            alignment=0,
            textColor=colors.white,
            spaceAfter=0,
        ),
        "lista": ParagraphStyle(
            "lista",
            parent=cuerpo,
            spaceAfter=2 * mm,
        ),
        "firma": ParagraphStyle(
            "firma",
            parent=cuerpo,
            fontSize=8.5,
            leading=11,
            alignment=TA_CENTER,
            spaceAfter=0,
        ),
    }


class _Paginado(pdf_canvas.Canvas):
    """Numera «Página 1 de 4», que es como lo dice el contrato firmado.

    El total solo se sabe cuando el documento está entero, así que las
    páginas se guardan y se escriben al cerrar: es el precio de poder decir
    «de cuántas», y en un documento que se firma eso importa -quien lo recibe
    tiene que poder comprobar que no le falta una hoja-.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paginas = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)

        for estado in self._paginas:
            self.__dict__.update(estado)
            self._pie_de_pagina(total)
            super().showPage()

        super().save()

    def _pie_de_pagina(self, total):
        self.setFont("Times-Roman", 7)
        self.setFillColor(GRIS)
        self.drawCentredString(
            PAGE_SIZE[0] / 2,
            9.5 * mm,
            f"Página {self._pageNumber} de {total}",
        )


def _marco(lienzo, documento, datos):
    """La cabecera y el pie que se repiten en todas las hojas.

    El contrato firmado lleva su código arriba en cada página y las oficinas
    abajo: una hoja suelta de un contrato tiene que poder identificarse sola.
    """

    lienzo.saveState()

    ancho = PAGE_SIZE[0]
    alto = PAGE_SIZE[1]

    # -----------------------------------------------------------------
    # CABECERA
    # -----------------------------------------------------------------
    lienzo.setFont("Helvetica-Bold", 13)
    lienzo.setFillColor(AZUL)
    lienzo.drawString(MARGEN_LATERAL, alto - 15 * mm, "TC telecable")

    lienzo.setFont("Helvetica-Bold", 6)
    lienzo.setFillColor(colors.HexColor("#1A8FD1"))
    lienzo.drawString(
        MARGEN_LATERAL,
        alto - 18.5 * mm,
        "#ConectandoOportunidades",
    )

    lienzo.setFont("Helvetica-Bold", 8.5)
    lienzo.setFillColor(AZUL)
    lienzo.drawRightString(
        ancho - MARGEN_LATERAL,
        alto - 15 * mm,
        datos["numero"],
    )

    lienzo.setFont("Helvetica", 7)
    lienzo.setFillColor(colors.HexColor("#64748B"))
    lienzo.drawRightString(
        ancho - MARGEN_LATERAL,
        alto - 18.5 * mm,
        datos["codigo_abonado"],
    )

    lienzo.setStrokeColor(AZUL)
    lienzo.setLineWidth(1.2)
    lienzo.line(
        MARGEN_LATERAL,
        alto - 21 * mm,
        ancho - MARGEN_LATERAL,
        alto - 21 * mm,
    )

    # -----------------------------------------------------------------
    # PIE
    # -----------------------------------------------------------------
    pie = " | ".join(
        parte
        for parte in (
            datos["oficinas"],
            f"Tel. {datos['telefono']}" if datos["telefono"] else "",
        )
        if parte
    )

    if pie:
        lienzo.setStrokeColor(AZUL_CLARO)
        lienzo.setLineWidth(0.8)
        lienzo.line(
            MARGEN_LATERAL,
            17 * mm,
            ancho - MARGEN_LATERAL,
            17 * mm,
        )

        lienzo.setFont("Times-Bold", 6.5)
        lienzo.setFillColor(GRIS)
        lienzo.drawCentredString(ancho / 2, 14 * mm, pie)

    lienzo.restoreState()


def _recuadro_de_las_partes(datos, estilos):
    """Empresa a la izquierda, abonado a la derecha, con su franja azul."""

    def celda(pares):
        return [
            Paragraph(f"<b>{etiqueta}:</b> {valor}", estilos["recuadro"])
            for etiqueta, valor in pares
        ]

    izquierda, derecha = datos_de_las_partes(datos)

    ancho_columna = (PAGE_SIZE[0] - 2 * MARGEN_LATERAL) / 2

    tabla = Table(
        [
            [
                Paragraph("DATOS DE LA EMPRESA", estilos["recuadro_cabecera"]),
                Paragraph(
                    "CÓDIGO DE CONTRATO / DATOS DEL ABONADO",
                    estilos["recuadro_cabecera"],
                ),
            ],
            [celda(izquierda), celda(derecha)],
        ],
        colWidths=[ancho_columna, ancho_columna],
    )

    tabla.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), AZUL),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, 0), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2 * mm),
                ("TOPPADDING", (0, 1), (-1, 1), 3 * mm),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 2 * mm),
                ("GRID", (0, 1), (-1, 1), 0.6, AZUL_CLARO),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )

    return tabla


def _lista(textos, estilos, numerada):
    return ListFlowable(
        [
            ListItem(
                Paragraph(texto, estilos["lista"]),
                leftIndent=6 * mm,
            )
            for texto in textos
        ],
        bulletType="1" if numerada else "bullet",
        bulletFontName="Times-Roman",
        bulletFontSize=9,
        leftIndent=6 * mm,
        spaceAfter=3 * mm,
    )


# Separación entre las dos líneas de firma. Es lo que las convierte en dos
# líneas y no en un trazo continuo de margen a margen: cada una tiene que
# leerse como el sitio donde firma una de las partes.
HUECO_ENTRE_FIRMAS = 24 * mm


def _firmas(datos, estilos):
    """Dos líneas para firmar, una por parte.

    Van en una tabla de tres columnas -firma, hueco, firma- porque la línea
    de ReportLab se dibuja sobre el borde de la celda: en dos columnas
    contiguas las dos líneas se tocan y salen como un solo trazo, que es lo
    que se ve en el papel cuando nadie ha firmado todavía.
    """

    empresa = datos["empresa"]

    ancho = PAGE_SIZE[0] - 2 * MARGEN_LATERAL
    ancho_firma = (ancho - HUECO_ENTRE_FIRMAS) / 2

    tabla = Table(
        [
            [
                [
                    Paragraph("<b>LA EMPRESA</b>", estilos["firma"]),
                    Paragraph(
                        empresa.business_name if empresa else "—",
                        estilos["firma"],
                    ),
                ],
                "",
                [
                    Paragraph("<b>EL ABONADO</b>", estilos["firma"]),
                    Paragraph(datos["cliente"], estilos["firma"]),
                    Paragraph(
                        f"{datos['documento_tipo']} {datos['documento_numero']}",
                        estilos["firma"],
                    ),
                ],
            ]
        ],
        colWidths=[ancho_firma, HUECO_ENTRE_FIRMAS, ancho_firma],
        hAlign="CENTER",
    )

    tabla.setStyle(
        TableStyle(
            [
                # Una línea por columna de firma; la del medio queda limpia.
                ("LINEABOVE", (0, 0), (0, 0), 0.8, GRIS),
                ("LINEABOVE", (2, 0), (2, 0), 0.8, GRIS),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )

    return tabla


def _cuerpo_del_contrato(datos, estilos):
    """Recorre los bloques del contrato y los dibuja."""

    titulo, subtitulo = titulo_del_contrato(datos)

    historia = [
        Paragraph(titulo, estilos["titulo"]),
        Paragraph(subtitulo, estilos["subtitulo"]),
    ]

    for tipo, contenido in bloques_del_contrato(datos):

        if tipo == "parrafo":
            historia.append(Paragraph(contenido, estilos["cuerpo"]))

        elif tipo == "clausula":
            historia.append(Paragraph(contenido, estilos["clausula"]))

        elif tipo == "lista":
            numerada, textos = contenido
            historia.append(_lista(textos, estilos, numerada=numerada))

        elif tipo == "recuadro":
            historia.append(_recuadro_de_las_partes(datos, estilos))
            historia.append(Spacer(1, 4 * mm))

        elif tipo == "cierre":
            historia.append(Spacer(1, 2 * mm))
            historia.append(Paragraph(contenido, estilos["cuerpo"]))

        elif tipo == "firmas":
            historia.append(Spacer(1, 20 * mm))
            historia.append(_firmas(datos, estilos))

        else:  # pragma: no cover - el vocabulario es cerrado
            raise ValueError(f"Bloque de contrato desconocido: {tipo}")

    return historia


def render_contract(contract, buffer):
    """Escribe el contrato en `buffer` y devuelve el nombre del archivo.

    El nombre es el número del contrato -«CONT-000001.pdf»-, que es como el
    operador lo va a buscar en su carpeta de descargas: el mismo texto que lee
    en la pantalla y en el papel.
    """

    datos = datos_del_contrato(contract)
    estilos = _estilos()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=MARGEN_LATERAL,
        rightMargin=MARGEN_LATERAL,
        topMargin=MARGEN_SUPERIOR,
        bottomMargin=MARGEN_INFERIOR,
        title=f"Contrato {datos['numero']} - {datos['cliente']}",
        author=datos["empresa"].business_name if datos["empresa"] else "",
        subject="Contrato de abonado para la prestación de servicios públicos",
    )

    marco = partial(_marco, datos=datos)

    documento.build(
        _cuerpo_del_contrato(datos, estilos),
        onFirstPage=marco,
        onLaterPages=marco,
        canvasmaker=_Paginado,
    )

    return f"{datos['numero']}.pdf"
