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
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas
from apps.organization import branding

from reportlab.platypus import (
    Flowable,
    KeepTogether,
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


def _logotipo(lienzo, alto_de_la_pagina):
    """La marca en la esquina de arriba, o nada si el archivo no está.

    Un despliegue sin la imagen tiene que poder entregar el contrato igual:
    el abonado no se queda sin su documento porque falte un dibujo. Cuando
    falta, la cabecera se queda con el código del contrato a la derecha, que
    es lo que identifica la hoja.

    El logotipo se apoya **sobre la línea azul** de la cabecera, no sobre el
    borde de la hoja: esa línea es la base de la franja, y colgar el dibujo
    de arriba lo dejaría bailando según el aire que traiga el archivo.
    """

    # El apaisado: la cabecera del contrato es una franja ancha y baja, y
    # el isotipo cuadrado del comprobante ahí sale como un sello suelto.
    ruta = branding.buscar_logo(stem=branding.STEM_APAISADO)

    if ruta is None:
        return

    try:
        dibujo = ImageReader(branding.logo_sin_margen(ruta))
        ancho_px, alto_px = dibujo.getSize()
    except Exception:
        # Un archivo a medio descargar no puede dejar sin contrato a nadie.
        return

    proporcion = (ancho_px / alto_px) if alto_px else 1

    lienzo.drawImage(
        dibujo,
        MARGEN_LATERAL,
        alto_de_la_pagina - 21 * mm + 1.5 * mm,
        width=ALTO_DEL_LOGO * proporcion,
        height=ALTO_DEL_LOGO,
        mask="auto",
        preserveAspectRatio=True,
        anchor="sw",
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
    _logotipo(lienzo, alto)

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

# Alto reservado encima de cada línea para firmar. Es el mismo con firma y
# sin ella: así el contrato ocupa lo mismo se haya firmado en el móvil o se
# vaya a firmar a mano, y las dos versiones del documento son la misma hoja.
ALTO_DEL_TRAZO = 18 * mm

# Lo que el sello de la empresa se separa de su línea: lo justo para que no
# la toque, sin flotar por encima. El trazo del abonado no lleva ninguna,
# porque a mano se firma sobre la línea.
#
# De paso decide su tamaño: el alto del sello es el del hueco menos este
# aire, así que acercarlo a la línea es lo mismo que agrandarlo.
SEPARACION_DEL_SELLO = 1 * mm

# Alto del logotipo en la cabecera. Manda el alto y no el ancho porque la
# cabecera es una franja: lo que no puede pasarse es de alta, y el ancho sale
# de la proporción del dibujo, sea el de hoy u otro que lo sustituya.
#
# Once milímetros para el logotipo apaisado: cuatro veces más ancho que alto,
# así que subirlo lo lanza a lo ancho de media cabecera.
ALTO_DEL_LOGO = 11 * mm


class _HuecoDeLaFirma(Flowable):
    """El espacio donde firma el abonado, y el trazo dentro si ya firmó.

    Es un flowable propio y no una `Image` dentro de la celda porque hace dos
    cosas que una imagen no puede:

    1. **Reserva el hueco esté firmado o no.** Así el contrato ocupa lo mismo
       se haya firmado en el móvil o se vaya a firmar a mano, y las dos
       versiones del documento son la misma hoja.
    2. **Dice dónde acabó.** Al dibujarse conoce su posición en la página, y
       la anota en `ancla`. Esa anotación es la que permite al visor del
       técnico poner la firma exactamente sobre la misma línea que el papel:
       el sitio lo decide el documento una sola vez, aquí, y no se vuelve a
       calcular en el navegador con otra fórmula que podría no coincidir.

    Si el técnico movió o agrandó la firma, ese ajuste llega en `colocacion`
    y se aplica **relativo al hueco**, nunca a la página: si mañana el
    contrato gana un párrafo y el bloque de firmas baja media hoja, la firma
    baja con él en vez de quedarse flotando donde estaba.
    """

    def __init__(self, ancho, alto, firma=None, ancla=None, separacion=0):
        super().__init__()

        self.width = ancho
        self.height = alto
        self._firma = firma
        self._ancla = ancla
        # Aire entre el dibujo y la línea. El trazo del abonado se apoya en
        # ella, como cuando se firma a mano; un sello estampado queda mejor
        # despegado, que es como cae un tampón sobre el papel.
        self._separacion = separacion

    def wrap(self, *args):
        return self.width, self.height

    def _medidas_del_trazo(self):
        """Dónde y de qué tamaño va el trazo dentro del hueco.

        Por defecto: centrado y apoyado en la línea, con el alto del hueco.
        Es la colocación que el papel daba antes de que se pudiera mover, y
        la que sigue valiendo para toda firma que nadie haya ajustado.
        """

        firma = self._firma

        ancho_px, alto_px = ImageReader(BytesIO(firma["imagen"])).getSize()
        proporcion = (alto_px / ancho_px) if ancho_px else 1

        # El alto disponible es el del hueco menos el aire que se le deje a
        # la línea: subir el dibujo sin encogerlo se comería el espacio de
        # arriba y el bloque de firmas crecería.
        disponible = self.height - self._separacion

        # Se escala por proporción y no a una medida fija: una firma ancha y
        # otra apretada salen del mismo lienzo con formas distintas, y
        # estirarlas al mismo rectángulo las deformaría.
        ancho = min(
            self.width,
            disponible / proporcion if proporcion else self.width,
        )

        colocacion = firma.get("colocacion") or {}
        ancho = float(colocacion.get("ancho") or ancho)
        alto = ancho * proporcion

        x = colocacion.get("x")
        y = colocacion.get("y")

        if x is None:
            x = (self.width - ancho) / 2
        if y is None:
            y = self._separacion

        return float(x), float(y), ancho, alto

    def draw(self):
        trazo = self._medidas_del_trazo() if self._firma else None

        if self._ancla is not None:
            x, y = self.canv.absolutePosition(0, 0)
            self._ancla.update({
                "pagina": self.canv.getPageNumber(),
                "x": x,
                "y": y,
                "ancho": self.width,
                "alto": self.height,
                "pagina_ancho": PAGE_SIZE[0],
                "pagina_alto": PAGE_SIZE[1],
                # Dónde acabó el trazo, si lo hay. El visor lo necesita para
                # dejar que el técnico lo vuelva a coger: sin esto tendría
                # que repetir la regla de colocación por su cuenta, y una
                # firma centrada «por el papel» no está en ningún campo que
                # pueda leer.
                "trazo": (
                    {
                        "x": trazo[0],
                        "y": trazo[1],
                        "ancho": trazo[2],
                        "alto": trazo[3],
                    }
                    if trazo
                    else None
                ),
            })

        if not trazo:
            return

        x, y, ancho, alto = trazo

        # `mask="auto"` respeta la transparencia del PNG: sin ella el trazo
        # llegaría dentro de un recuadro blanco que taparía la línea.
        self.canv.drawImage(
            ImageReader(BytesIO(self._firma["imagen"])),
            x,
            y,
            width=ancho,
            height=alto,
            mask="auto",
        )


def _firmas(datos, estilos, ancla=None):
    """Dos líneas para firmar, una por parte, con el trazo encima.

    Van en una tabla de tres columnas -firma, hueco, firma- porque la línea
    de ReportLab se dibuja sobre el borde de la celda: en dos columnas
    contiguas las dos líneas se tocan y salen como un solo trazo, que es lo
    que se ve en el papel cuando nadie ha firmado todavía.

    La fila de arriba es el espacio donde se firma. La empresa firma el
    ejemplar impreso, así que su lado queda en blanco a propósito.
    """

    empresa = datos["empresa"]
    sello = datos.get("firma_empresa")

    ancho = PAGE_SIZE[0] - 2 * MARGEN_LATERAL
    ancho_firma = (ancho - HUECO_ENTRE_FIRMAS) / 2

    hueco = _HuecoDeLaFirma(
        ancho_firma,
        ALTO_DEL_TRAZO,
        firma=datos.get("firma_abonado"),
        ancla=ancla,
    )

    # El sello de la empresa ocupa su hueco igual que el trazo del abonado el
    # suyo, pero no se mueve ni se ajusta: no lo firma nadie en el momento,
    # va impreso. Y va algo despegado de la línea, que es como queda un
    # tampón sobre el papel y como lo pidió administración.
    hueco_empresa = _HuecoDeLaFirma(
        ancho_firma,
        ALTO_DEL_TRAZO,
        firma={"imagen": sello} if sello else None,
        separacion=SEPARACION_DEL_SELLO,
    )

    tabla = Table(
        [
            [hueco_empresa, "", hueco],
            [
                [
                    Paragraph("<b>LA EMPRESA</b>", estilos["firma"]),
                    # La razón social se escribe debajo aunque el sello la
                    # traiga dentro: el sello es un escaneo y el pie de firma
                    # es el dato, que tiene que leerse igual de bien en una
                    # fotocopia.
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
            ],
        ],
        colWidths=[ancho_firma, HUECO_ENTRE_FIRMAS, ancho_firma],
        rowHeights=[ALTO_DEL_TRAZO, None],
        hAlign="CENTER",
    )

    tabla.setStyle(
        TableStyle(
            [
                # Una línea por columna de firma; la del medio queda limpia.
                ("LINEABOVE", (0, 1), (0, 1), 0.8, GRIS),
                ("LINEABOVE", (2, 1), (2, 1), 0.8, GRIS),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                # El trazo se apoya en la línea; los datos cuelgan de ella.
                ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),
                ("VALIGN", (0, 1), (-1, 1), "TOP"),
            ]
        )
    )

    return tabla


def _cuerpo_del_contrato(datos, estilos, ancla=None):
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
            # El bloque entero pasa de página junto o no pasa. ReportLab
            # parte las tablas por filas, y aquí eso significaba dejar el
            # trazo del abonado al pie de una hoja y su línea -con el nombre
            # de quien firma- al principio de la siguiente. Una firma sola en
            # una página no es la firma de nada.
            historia.append(
                KeepTogether([
                    Spacer(1, 6 * mm),
                    _firmas(datos, estilos, ancla=ancla),
                ])
            )

        else:  # pragma: no cover - el vocabulario es cerrado
            raise ValueError(f"Bloque de contrato desconocido: {tipo}")

    return historia


def render_contract(contract, buffer, ancla=None, con_firma=True):
    """Escribe el contrato en `buffer` y devuelve el nombre del archivo.

    El nombre es el número del contrato -«CONT-000001.pdf»-, que es como el
    operador lo va a buscar en su carpeta de descargas: el mismo texto que lee
    en la pantalla y en el papel.

    `con_firma=False` dibuja el contrato sin el trazo, aunque esté firmado.

    `ancla`, si se pasa, se rellena con la página y las medidas del hueco de
    la firma -y del trazo dentro de él- tal como quedaron en **este**
    documento. Lo necesita el visor del
    técnico para poner el trazo sobre la misma línea que el papel, y sale de
    aquí y no de una fórmula aparte para que no haya dos versiones de dónde se
    firma.
    """

    datos = datos_del_contrato(contract)
    estilos = _estilos()

    if not con_firma:
        # El contrato tal como estaba antes de firmarlo. Se sirve así
        # mientras el técnico mueve la firma en pantalla: con el trazo
        # dibujado debajo, arrastrarlo dejaría dos firmas a la vista y
        # ninguna de las dos sería la que se va a guardar.
        datos = dict(datos, firma_abonado=None)

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
        _cuerpo_del_contrato(datos, estilos, ancla=ancla),
        onFirstPage=marco,
        onLaterPages=marco,
        canvasmaker=_Paginado,
    )

    return f"{datos['numero']}.pdf"
