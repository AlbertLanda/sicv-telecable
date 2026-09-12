"""El comprobante en papel, dibujado con ReportLab.

Reproduce la representación impresa del sistema que se reemplaza: cabecera con
el logotipo y la razón social, el recuadro del RUC con el tipo de documento y
su serie-número, la caja del abonado, el detalle línea a línea y, abajo, el
importe en letras, el QR y el recuadro de importes.

Quién emite ese papel no lo decide esta función: lo decide el talonario que el
operador eligió al cobrar. El block B001 imprime CABLE LOS ANDES y el
S010-SPEEDY imprime SPEEDY QUANTICO, con su RUC y su título, igual que cada
uno lleva su propio correlativo.

Vive aparte de las vistas porque el papel tiene reglas propias -medidas,
márgenes, dónde parte una tabla larga- que no son las de una pantalla. La
aritmética que declara -IGV, descuentos, importe en letras- vive aparte de
aquí, en `invoicing`, para poder comprobarla sin abrir un PDF y mirarlo.
"""

import base64
import hashlib
from pathlib import Path

from django.conf import settings

from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .invoicing import amount_in_words, receipt_lines, receipt_totals
from .models import format_receipt_number


# Media hoja apaisada, que es el tamaño en que se entrega este papel: dos por
# hoja A4 y cabe en el sobre del abonado. El formato manda sobre el contenido
# -la tabla del detalle se parte sola si un cobro cubre muchos meses-, así que
# cambiar esto no rompe nada, solo cambia dónde corta.
PAGE_SIZE = landscape(A5)

# Dónde se busca el logotipo.
#
# En MEDIA_ROOT: hoy es un archivo que se deja en su sitio, no algo que venga
# con el código. Provisional a propósito -está pendiente decidir si cada razón
# social lleva el suyo, y entonces será un campo del emisor y no una ruta
# fija-, así que se deja en una sola constante y nada más del módulo sabe
# dónde está.
LOGO_DIR = Path(settings.MEDIA_ROOT)
LOGO_STEM = "telecable-logo"

# Cualquier extensión, y cualquier cosa pegada detrás del nombre. El archivo
# llega descargado de un navegador o de un chat, que le añaden lo suyo -
# «telecable-logo.jpg.jpeg» es lo que salió la primera vez-, y el fallo es
# mudo: el papel se imprime igual y sin logo. Exigir el nombre exacto costaba
# una vuelta entera para descubrir que sobraba una extensión.
LOGO_PATTERN = f"{LOGO_STEM}*"

# Con varios candidatos gana el primero de esta lista. Un PNG antes que un
# JPG porque conserva la transparencia, que en una cabecera se nota.
LOGO_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")

NEGRO = colors.black
LINEA = colors.HexColor("#000000")

# Esquinas de las cajas. Leve a propósito: lo justo para quitarles la punta,
# sin que el papel deje de parecer un comprobante. Un radio grande lo acerca a
# una tarjeta de pantalla, y este documento se lee junto a otros en papel.
#
# Se declara una vez y se reparte a las cuatro cajas -RUC, abonado, detalle e
# importes- porque cuando cuatro esquinas se dibujan por separado, la primera
# que alguien retoca deja a las otras tres distintas.
RADIO = 1.6 * mm
ESQUINAS = ("ROUNDEDCORNERS", [RADIO, RADIO, RADIO, RADIO])

# Alto de la fila de cabecera de la tabla del detalle.
ALTO_CABECERA = 7.5 * mm

# Lo que mide la fila vacía del final cuando no sobra hueco que repartir -un
# cobro de muchas líneas-. No es cero: sin ella, la última línea queda pegada
# al borde de la caja.
RELLENO_MINIMO = 4 * mm

# Lo que el marco de la página reserva arriba y abajo por su cuenta. Es el
# valor por defecto de ReportLab y no aparece en `documento.height`.
FRAME_PADDING = 6


def _estilos():
    base = getSampleStyleSheet()
    normal = base["Normal"]

    def estilo(nombre, size, leading, **extra):
        return ParagraphStyle(
            nombre, parent=normal, fontSize=size, leading=leading, **extra
        )

    # Los cuerpos van en proporcion al papel del sistema que se reemplaza, no
    # al minimo legible: este comprobante se lee a un brazo de distancia sobre
    # un mostrador, a veces con el abonado mirandolo del otro lado, y la
    # primera version se quedaba pequeña para eso.
    return {
        "empresa": estilo("empresa", 15, 17.5, fontName="Helvetica"),
        "empresa_pie": estilo("empresa_pie", 7.2, 8.8),
        "ruc": estilo("ruc", 12, 14.5, fontName="Helvetica-Bold", alignment=1),
        "titulo": estilo("titulo", 11.5, 14, fontName="Helvetica-Bold", alignment=1),
        "etiqueta": estilo("etiqueta", 8, 10, fontName="Helvetica-Bold"),
        "dato": estilo("dato", 8, 10),
        "th": estilo("th", 8, 10, fontName="Helvetica-Bold", alignment=1),
        "celda": estilo("celda", 7.5, 9.5),
        "num": estilo("num", 7.5, 9.5, alignment=2),
        "pie": estilo("pie", 7.5, 9.8),
        "anulado": estilo(
            "anulado", 11, 13,
            fontName="Helvetica-Bold",
            alignment=1,
            textColor=colors.HexColor("#a52f22"),
        ),
    }


def find_logo():
    """El archivo del logotipo, o None si no hay ninguno.

    Con varios candidatos gana el de mejor extensión y, a igualdad, el de
    nombre más corto: entre «telecable-logo.png» y «telecable-logo (1).png»
    se queda con el limpio, que es el que alguien puso a propósito.
    """
    if not LOGO_DIR.exists():
        return None

    candidatos = [
        ruta for ruta in LOGO_DIR.glob(LOGO_PATTERN) if ruta.is_file()
    ]

    if not candidatos:
        return None

    def preferencia(ruta):
        suffix = ruta.suffix.lower()
        puesto = (
            LOGO_SUFFIXES.index(suffix)
            if suffix in LOGO_SUFFIXES
            else len(LOGO_SUFFIXES)
        )

        return (puesto, len(ruta.name), ruta.name)

    return sorted(candidatos, key=preferencia)[0]


def _logo(alto):
    """El logotipo, o nada si no se puede dibujar.

    Un despliegue sin la imagen -o con una descargada a medias- tiene que
    poder entregar el papel igual: la ventanilla no puede quedarse parada
    porque falte o se rompa un dibujo. Quien quiera saber si el sistema lo
    encuentra tiene `manage.py comprobar_logo`, que sí lo dice.
    """
    ruta = find_logo()

    if ruta is None:
        return ""

    try:
        imagen = Image(str(ruta))
        proporcion = imagen.imageWidth / imagen.imageHeight
    except Exception:
        return ""

    imagen.drawHeight = alto
    imagen.drawWidth = alto * proporcion

    return imagen


def _cabecera(receipt, estilos, ancho):
    """Logotipo, razón social y el recuadro del RUC con el tipo de documento."""
    sequence = receipt.sequence
    issuer = sequence.issuer

    identidad = [
        Paragraph(issuer.business_name if issuer else "", estilos["empresa"]),
    ]

    if issuer and issuer.address:
        identidad.append(Paragraph(issuer.address, estilos["empresa_pie"]))

    if issuer and issuer.phone:
        identidad.append(
            Paragraph(f"Teléfono {issuer.phone}", estilos["empresa_pie"])
        )

    recuadro = Table(
        [
            [Paragraph(f"R.U.C. {issuer.ruc if issuer else ''}", estilos["ruc"])],
            [Paragraph(sequence.document_title, estilos["titulo"])],
            [Paragraph(
                f"{receipt.series}-{format_receipt_number(receipt.number)}",
                estilos["ruc"],
            )],
        ],
        colWidths=[68 * mm],
    )
    recuadro.setStyle(
        TableStyle([
            ("BOX", (0, 0), (-1, -1), 1.1, LINEA),
            ESQUINAS,
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )

    tabla = Table(
        [[_logo(13 * mm), identidad, recuadro]],
        colWidths=[26 * mm, ancho - 26 * mm - 68 * mm, 68 * mm],
    )
    tabla.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (1, 0), "TOP"),
            ("VALIGN", (2, 0), (2, 0), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
    )

    return tabla


def _abonado(receipt, estilos, ancho):
    """La caja del abonado: a quién se le cobró y cuándo."""
    payment = receipt.payment
    customer = payment.customer
    direccion = customer.addresses.filter(is_primary=True).first()

    def par(etiqueta, valor):
        return [
            Paragraph(etiqueta, estilos["etiqueta"]),
            Paragraph(valor or "", estilos["dato"]),
        ]

    izquierda = Table(
        [
            par("Abonado", str(customer)),
            par(customer.get_document_type_display(), customer.document_number),
            par("Código", customer.code),
            par("Dirección", direccion.address if direccion else ""),
        ],
        colWidths=[16 * mm, 96 * mm],
    )

    derecha = Table(
        [
            par("F. Emisión", receipt.issued_at.strftime("%d/%m/%Y %H:%M:%S")),
            par("Moneda", "SOLES"),
        ],
        colWidths=[18 * mm, 34 * mm],
    )

    interno = TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6),
    ])
    izquierda.setStyle(interno)
    derecha.setStyle(interno)

    caja = Table(
        [[izquierda, derecha]],
        colWidths=[ancho - 56 * mm, 56 * mm],
    )
    caja.setStyle(
        TableStyle([
            ("BOX", (0, 0), (-1, -1), 1.1, LINEA),
            ESQUINAS,
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )

    return caja


def _detalle(receipt, estilos, ancho, lines, relleno=RELLENO_MINIMO):
    """El detalle línea a línea, con las columnas del papel.

    `relleno` es el alto de la fila vacía del final. Lo calcula quien arma la
    hoja, con el hueco que sobra: la caja se estira hasta el pie en vez de
    dejar la mitad de abajo en blanco, que es como se ve el papel del sistema
    que se reemplaza y lo que hace que un comprobante de una línea y otro de
    cinco tengan la misma silueta.
    """
    anchos = [16 * mm, 17 * mm, ancho - 107 * mm, 26 * mm, 22 * mm, 26 * mm]

    datos = [[
        Paragraph(texto, estilos["th"])
        for texto in (
            "Cantidad", "Unidad", "Descripción",
            "Precio unitario", "Descuento", "Total",
        )
    ]]

    for linea in lines:
        datos.append([
            Paragraph(f"{linea['quantity']:.5f}", estilos["celda"]),
            Paragraph(linea["unit"], estilos["celda"]),
            Paragraph(linea["description"], estilos["celda"]),
            Paragraph(f"{linea['unit_price']:.6f}", estilos["num"]),
            Paragraph(f"{linea['discount']:.2f}", estilos["num"]),
            Paragraph(f"{linea['total']:.2f}", estilos["num"]),
        ])

    if not lines:
        datos.append([
            Paragraph(
                "El pago no se aplicó a ninguna deuda: quedó como saldo a "
                "favor del abonado.",
                estilos["celda"],
            ),
            "", "", "", "", "",
        ])

    # El relleno va como una fila sin texto y no como un margen, para que las
    # rayas verticales de las columnas lleguen abajo igual que en el papel del
    # sistema anterior.
    datos.append([""] * 6)

    tabla = Table(
        datos,
        colWidths=anchos,
        rowHeights=[ALTO_CABECERA] + [None] * (len(datos) - 2) + [relleno],
        repeatRows=1,
    )

    estilo = [
        ("BOX", (0, 0), (-1, -1), 1.1, LINEA),
        ESQUINAS,
        ("LINEBELOW", (0, 0), (-1, 0), 1.1, LINEA),
        ("LINEBEFORE", (1, 0), (-1, -1), 0.7, LINEA),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 1), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 1.5),
        ("ALIGN", (0, 1), (1, -1), "CENTER"),
    ]

    if not lines:
        estilo.append(("SPAN", (0, 1), (-1, 1)))

    tabla.setStyle(TableStyle(estilo))

    return tabla


def _qr(receipt, totals, tamaño):
    """El código del comprobante, con los datos que lo identifican.

    Lleva el orden con el que SUNAT los publica -emisor, tipo, serie, número,
    IGV, total, fecha y documento del receptor- para que el día que el papel
    sea un comprobante declarado, el contenido ya sea el que toca y solo haya
    que firmarlo.
    """
    issuer = receipt.sequence.issuer
    customer = receipt.payment.customer

    contenido = "|".join([
        issuer.ruc if issuer else "",
        receipt.sequence.document_title,
        receipt.series,
        format_receipt_number(receipt.number),
        f"{totals['igv']:.2f}",
        f"{totals['total']:.2f}",
        receipt.issued_at.strftime("%Y-%m-%d"),
        customer.document_type,
        customer.document_number,
    ])

    widget = qr.QrCodeWidget(contenido)
    limites = widget.getBounds()
    ancho = limites[2] - limites[0]
    alto = limites[3] - limites[1]

    dibujo = Drawing(
        tamaño, tamaño, transform=[tamaño / ancho, 0, 0, tamaño / alto, 0, 0]
    )
    dibujo.add(widget)

    return dibujo


def _resumen(receipt, totals):
    """El resumen del documento, en la línea de abajo.

    NO es la firma digital de SUNAT: esa se calcula sobre el XML firmado y hoy
    este papel no es un comprobante declarado. Es un resumen de sus propios
    datos, que cambia si alguno cambia, y ocupa el sitio que le corresponde
    para que el día de la declaración solo haya que sustituirlo.
    """
    semilla = "|".join([
        receipt.full_number,
        str(receipt.issued_at.isoformat()),
        f"{totals['total']:.2f}",
        receipt.payment.customer.document_number,
    ]).encode("utf-8")

    return base64.b64encode(hashlib.sha1(semilla).digest()).decode()[:28]


def _pie(receipt, estilos, ancho, totals):
    """Importe en letras, QR y el recuadro de importes."""
    payment = receipt.payment
    pagado = payment.paid_at or payment.received_at

    izquierda = [
        Paragraph(
            f"SON: {amount_in_words(totals['total'])}", estilos["pie"]
        ),
        Paragraph(
            "Fecha de vencimiento: "
            f"{payment.due_date.strftime('%d/%m/%Y') if payment.due_date else ''}",
            estilos["pie"],
        ),
        Paragraph(
            "Fecha de cancelación: "
            f"{pagado.strftime('%d/%m/%Y') if pagado else ''}",
            estilos["pie"],
        ),
        Spacer(1, 4 * mm),
        Paragraph(f"Resumen: {_resumen(receipt, totals)}", estilos["pie"]),
        Paragraph(
            f"Representación impresa de {receipt.sequence.document_title}",
            estilos["pie"],
        ),
    ]

    importes = Table(
        [
            [Paragraph(etiqueta, estilos["pie"]),
             Paragraph(f"S/{valor:.2f}", estilos["num"])]
            for etiqueta, valor in (
                ("Op. Gravada", totals["gravada"]),
                ("Op. Exonerada", totals["exonerada"]),
                ("Op. Inafecta", totals["inafecta"]),
                ("Op. Gratuita", totals["gratuita"]),
                ("Total Dscto", totals["discount"]),
                ("I.G.V.", totals["igv"]),
                ("Importe Total", totals["total"]),
            )
        ],
        colWidths=[28 * mm, 24 * mm],
    )
    importes.setStyle(
        TableStyle([
            ("BOX", (0, 0), (-1, -1), 1.1, LINEA),
            ESQUINAS,
            ("TOPPADDING", (0, 0), (-1, -1), 0.8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8),
            ("LEFTPADDING", (0, 0), (0, -1), 4),
            ("RIGHTPADDING", (-1, 0), (-1, -1), 4),
        ])
    )

    tabla = Table(
        [[izquierda, _qr(receipt, totals, 18 * mm), importes]],
        colWidths=[ancho - 52 * mm - 34 * mm, 34 * mm, 52 * mm],
    )
    tabla.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "CENTER"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ])
    )

    return tabla


def render_receipt(receipt, buffer):
    """Escribe el comprobante en `buffer` y devuelve el nombre del archivo.

    El nombre es el número completo -«B001-0041314.pdf»-, que es como el
    operador lo va a buscar en su carpeta de descargas: el mismo texto que lee
    en la pantalla y en el papel.
    """
    estilos = _estilos()
    lines = receipt_lines(receipt)
    totals = receipt_totals(receipt, lines)

    margen = 8 * mm
    ancho = PAGE_SIZE[0] - 2 * margen

    documento = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=margen,
        rightMargin=margen,
        topMargin=margen,
        bottomMargin=margen,
        title=receipt.full_number,
        author=str(receipt.sequence.issuer or "SICV"),
    )

    # Las piezas fijas: miden lo que miden y no se estiran.
    encabezado = []

    if receipt.is_voided:
        encabezado = [
            Paragraph(
                f"ANULADO — {receipt.payment.void_reason}", estilos["anulado"]
            ),
            Spacer(1, 2 * mm),
        ]

    cabecera = _cabecera(receipt, estilos, ancho)
    abonado = _abonado(receipt, estilos, ancho)
    pie = _pie(receipt, estilos, ancho, totals)
    separadores = [3.5 * mm, 3 * mm, 3 * mm]

    # El detalle se arma dos veces: la primera para saber cuánto ocupa por sí
    # solo, la segunda ya con el hueco que sobra metido en su fila vacía. Sin
    # esta cuenta, el pie quedaba a media hoja y el cuarto de abajo en blanco,
    # que es lo que distingue un comprobante de un borrador.
    detalle = _detalle(receipt, estilos, ancho, lines)

    ocupado = sum(separadores) + sum(
        pieza.wrap(ancho, documento.height)[1]
        for pieza in encabezado + [cabecera, abonado, detalle, pie]
    )

    # El marco de la página añade su propio relleno arriba y abajo, que no
    # está en `documento.height`. Descontarlo evita que el estirón empuje el
    # pie a una segunda hoja por unos milímetros.
    disponible = documento.height - 2 * FRAME_PADDING
    sobra = disponible - ocupado

    if sobra > 0:
        detalle = _detalle(
            receipt, estilos, ancho, lines, RELLENO_MINIMO + sobra
        )

    documento.build(
        encabezado
        + [
            cabecera,
            Spacer(1, separadores[0]),
            abonado,
            Spacer(1, separadores[1]),
            detalle,
            Spacer(1, separadores[2]),
            pie,
        ]
    )

    return f"{receipt.full_number}.pdf"
