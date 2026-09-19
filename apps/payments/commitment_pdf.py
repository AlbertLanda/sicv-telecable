"""El compromiso de pago en papel, para que el abonado lo firme.

No es un comprobante: no numera caja ni declara impuestos. Es la solicitud de
prórroga que el abonado firma y alguien autoriza, y por eso acaba en dos líneas
de firma en vez de en un recuadro de importes.

Reproduce el papel del sistema que se reemplaza: logotipo y teléfono arriba a
la izquierda, el título en medio, el número a la derecha, el texto de la
solicitud con las deudas que cubre, los tres recuadros de cuotas -importe,
vencimiento y corte-, y al pie quién es el abonado, quién lo representa y las
dos firmas.

Vive aparte de `pdf.py` porque no comparte nada con el comprobante salvo la
biblioteca: otro tamaño, otra retórica y otras piezas. Lo único que sí comparte
es de dónde sale el logotipo, y eso se importa.
"""

from datetime import timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .pdf import _logo


PAGE_SIZE = landscape(A5)

NEGRO = colors.black

# Tres recuadros de cuotas, cinco filas cada uno: quince, las mismas que ofrece
# el formulario. El papel las reparte en columnas en vez de en una lista larga
# porque asi cabe en media hoja con sitio para las firmas.
COLUMNAS_CUOTAS = 3
FILAS_POR_COLUMNA = 5

# Cuanto tarda en llegar el corte despues del vencimiento pactado.
#
# Un dia, como en el papel de referencia -vence el 23 y corta el 24-. Es del
# papel y no de la politica de cobro: la `cut_date` del cargo la calcula la
# politica sobre su propio vencimiento, y aqui lo que se promete es otra fecha.
DIAS_HASTA_EL_CORTE = 1


def _estilos():
    base = getSampleStyleSheet()
    normal = base["Normal"]

    def estilo(nombre, size, leading, **extra):
        return ParagraphStyle(
            nombre, parent=normal, fontSize=size, leading=leading, **extra
        )

    return {
        "titulo": estilo(
            "c_titulo", 14, 17, fontName="Helvetica-Bold", alignment=1
        ),
        "numero": estilo(
            "c_numero", 13, 16, fontName="Helvetica-Bold", alignment=2
        ),
        "telefono": estilo("c_telefono", 6.5, 8, fontName="Helvetica-Bold"),
        "fuerte": estilo("c_fuerte", 8.5, 11, fontName="Helvetica-Bold"),
        "texto": estilo("c_texto", 8.5, 13),
        "th": estilo("c_th", 7.5, 9.5, fontName="Helvetica-Bold"),
        "celda": estilo("c_celda", 7.5, 9.5),
        "firma": estilo("c_firma", 7.5, 9.5, fontName="Helvetica-Bold", alignment=1),
        "puntos": estilo("c_puntos", 7.5, 9.5, alignment=1),
    }


def commitment_number(commitment):
    """El número del compromiso tal como sale impreso: «002671»."""
    return f"{commitment.pk:06d}"


def _cabecera(commitment, estilos, ancho, issuer):
    """Logotipo con el teléfono debajo, el título en medio y el número."""
    marca = []

    logo = _logo(15 * mm)

    if logo:
        marca.append(logo)

    if issuer and issuer.phone:
        marca.append(
            Paragraph(
                f"- Telf. {issuer.phone}",
                estilos["telefono"],
            )
        )

    if not marca:
        marca.append(
            Paragraph(
                "",
                estilos["telefono"],
            )
        )

    tabla = Table(
        [[
            marca,
            Paragraph("COMPROMISO DE PAGO", estilos["titulo"]),
            Paragraph(
                f"Nº {commitment_number(commitment)}", estilos["numero"]
            ),
        ]],
        colWidths=[42 * mm, ancho - 42 * mm - 40 * mm, 40 * mm],
    )
    tabla.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (0, 0), "TOP"),
            ("VALIGN", (1, 0), (-1, 0), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
    )

    return tabla


def _solicitud(commitment, estilos, issuer):
    """El texto de la solicitud, con las deudas que se piden aplazar."""
    empresa = issuer.business_name if issuer else ""
    deudas = ", ".join(
        charge.description for charge in commitment.charges.all()
    )

    return [
        Paragraph("SEÑORES", estilos["fuerte"]),
        Paragraph(empresa, estilos["fuerte"]),
        Spacer(1, 3.5 * mm),
        Paragraph(
            "Por intermedio de la presente solicito se sirva concederme una "
            "prorroga para efectuar los pagos correspondientes a:",
            estilos["texto"],
        ),
        Paragraph(deudas or "—", estilos["texto"]),
        Spacer(1, 3 * mm),
        Paragraph(
            f"Por lo que me comprometo a acercarme a la oficina de {empresa} "
            "y efectuar el pago correspondiente en la fecha indicada.",
            estilos["texto"],
        ),
    ]


def commitment_rows(commitment):
    """Las filas de importe, vencimiento y corte que van en los recuadros.

    Salen del plan de cuotas. Sin plan se imprime **una** fila con el total y
    la fecha del compromiso: es lo que se pactó, y dejar los recuadros vacíos
    daría un papel que el abonado firma sin que diga cuánto ni cuándo.
    """
    cuotas = list(commitment.installments.all())

    if not cuotas:
        return [(commitment.amount, commitment.committed_date)]

    return [(cuota.amount, cuota.due_date) for cuota in cuotas]


def _recuadros(commitment, estilos, ancho):
    """Los tres recuadros de cuotas, uno al lado del otro."""
    filas = commitment_rows(commitment)
    ancho_columna = (ancho - 2 * 4 * mm) / COLUMNAS_CUOTAS
    recuadros = []

    for columna in range(COLUMNAS_CUOTAS):
        trozo = filas[
            columna * FILAS_POR_COLUMNA : (columna + 1) * FILAS_POR_COLUMNA
        ]

        datos = [[
            Paragraph("Importe", estilos["th"]),
            Paragraph("Vencimiento", estilos["th"]),
            Paragraph("Corte", estilos["th"]),
        ]]

        for importe, vence in trozo:
            corte = vence + timedelta(days=DIAS_HASTA_EL_CORTE)
            datos.append([
                Paragraph(f"{importe:.2f}", estilos["celda"]),
                Paragraph(vence.strftime("%d/%m/%Y"), estilos["celda"]),
                Paragraph(corte.strftime("%d/%m/%Y"), estilos["celda"]),
            ])

        # Las filas que sobran van en blanco: el recuadro tiene el mismo alto
        # esté lleno o vacío, como el papel impreso que se rellena a mano.
        for _ in range(FILAS_POR_COLUMNA - len(trozo)):
            datos.append(["", "", ""])

        recuadro = Table(
            datos,
            colWidths=[ancho_columna * 0.3, ancho_columna * 0.38, ancho_columna * 0.32],
            rowHeights=[5.2 * mm] + [4.6 * mm] * FILAS_POR_COLUMNA,
        )
        recuadro.setStyle(
            TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.9, NEGRO),
                ("LINEBELOW", (0, 0), (-1, 0), 0.9, NEGRO),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ])
        )
        recuadros.append(recuadro)

    fila = Table(
        [recuadros],
        colWidths=[ancho_columna + 4 * mm] * COLUMNAS_CUOTAS,
    )
    fila.setStyle(
        TableStyle([
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )

    return fila


def _identidad(commitment, estilos, ancho):
    """Quién firma: el abonado, su documento y quién lo representa."""
    customer = commitment.customer
    direccion = customer.addresses.filter(is_primary=True).first()

    def par(etiqueta, valor):
        return [
            Paragraph(etiqueta, estilos["fuerte"]),
            Paragraph(valor or "", estilos["texto"]),
        ]

    filas = [
        par("Importe total:", f"{commitment.amount:.2f}") + ["", ""],
        par("Abonado:", str(customer).upper())
        + par("D.N.I.:", customer.document_number),
        par("Dirección:", (direccion.address if direccion else "").upper())
        + par("Código:", customer.code),
        par("Representante:", commitment.representative.upper())
        + par("D.N.I.:", commitment.representative_document),
    ]

    etiqueta = 26 * mm
    documento = 18 * mm
    tabla = Table(
        filas,
        colWidths=[
            etiqueta,
            ancho - etiqueta - documento - 42 * mm,
            documento,
            42 * mm,
        ],
    )
    tabla.setStyle(
        TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1.4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )

    return tabla


def _firmas(estilos, ancho):
    """Las dos rayas del pie: quien se compromete y quien lo autoriza."""
    puntos = "." * 46

    tabla = Table(
        [
            [
                Paragraph(puntos, estilos["puntos"]),
                Paragraph(puntos, estilos["puntos"]),
            ],
            [
                Paragraph("Firma del abonado", estilos["firma"]),
                Paragraph("Autorizado por", estilos["firma"]),
            ],
        ],
        colWidths=[ancho / 2, ancho / 2],
    )
    tabla.setStyle(
        TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
    )

    return tabla


def render_commitment(commitment, buffer, issuer=None):
    """Escribe el compromiso en `buffer` y devuelve el nombre del archivo."""
    from .models import Issuer

    if issuer is None:
        # Nada ata todavía un compromiso a una empresa del grupo: no lo emite
        # un talonario, como sí hace el comprobante. Se toma la primera activa,
        # que es la que el papel del sistema anterior lleva impresa.
        issuer = Issuer.objects.filter(is_active=True).first()

    estilos = _estilos()
    margen = 10 * mm
    ancho = PAGE_SIZE[0] - 2 * margen

    documento = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=margen,
        rightMargin=margen,
        topMargin=margen,
        bottomMargin=margen,
        title=f"Compromiso {commitment_number(commitment)}",
        author=str(issuer or "SICV"),
    )

    historia = [
        _cabecera(commitment, estilos, ancho, issuer),
        Spacer(1, 4 * mm),
        *_solicitud(commitment, estilos, issuer),
        Spacer(1, 4 * mm),
        _recuadros(commitment, estilos, ancho),
        Spacer(1, 4 * mm),
        _identidad(commitment, estilos, ancho),
        Spacer(1, 11 * mm),
        _firmas(estilos, ancho),
    ]

    documento.build(historia)

    return f"compromiso-{commitment_number(commitment)}.pdf"
