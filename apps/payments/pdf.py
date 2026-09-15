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
from io import BytesIO
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

from .invoicing import (
    IGV_RATE,
    amount_in_words,
    receipt_lines,
    receipt_totals,
    payment_condition,
    sunat_receiver_document,
)
from .models import ReceiptSequence, format_receipt_number


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

# Cuanto se puede apartar un pixel del blanco para seguir siendo margen.
#
# Un umbral y no igualdad exacta: el archivo de hoy es un JPEG, y un JPEG no
# guarda el blanco exacto -lo deja en 250 y pico-, asi que comparar a pelo no
# recortaria nada. Bajo, para no comerse un trazo claro del dibujo.
UMBRAL_BLANCO = 18

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
# El logotipo de la media hoja y la columna en la que vive.
#
# Se mide contra el recuadro del RUC que tiene enfrente, que es la otra pieza
# de la cabecera: los dos rondan los 24 mm de alto y la franja queda
# equilibrada. A 13 mm el logotipo llenaba media columna y dejaba el resto en
# aire, con la razon social al lado a 15 pt: se leia como un icono perdido en
# la esquina y no como la marca de quien emite el papel.
ALTO_LOGO_HOJA = 24 * mm
COLUMNA_LOGO_HOJA = 30 * mm

ALTO_CABECERA = 7.5 * mm

# Lo que mide la fila vacía del final cuando no sobra hueco que repartir -un
# cobro de muchas líneas-. No es cero: sin ella, la última línea queda pegada
# al borde de la caja.
RELLENO_MINIMO = 4 * mm

# Lo que el marco de la página reserva arriba y abajo por su cuenta. Es el
# valor por defecto de ReportLab y no aparece en `documento.height`.
FRAME_PADDING = 6


# ------------------------------------------------------------------
# El tique de boleta.
#
# Los blocks B001..B007 se entregan en un rollo estrecho, no en la media hoja
# apaisada: todo en una columna, centrado arriba y alineado abajo. Cual de los
# dos formatos toca lo dice el talonario (`print_format`), no la letra de la
# serie -los blocks de un cobrador tambien son boletas y van en media hoja-.
# ------------------------------------------------------------------

# Ancho de rollo de 80 mm, que es el papel de la impresora de tiques.
ANCHO_TIQUE = 80 * mm
MARGEN_TIQUE = 4 * mm

# El alto se calcula midiendo el contenido: un tique es tan largo como lo que
# tiene que decir. Fijarlo dejaria media cuarta en blanco en un cobro de una
# linea y cortaria uno de diez.
ALTO_TIQUE_MINIMO = 120 * mm
COLA_TIQUE = 6 * mm

# Alto del logotipo. La imagen es casi cuadrada, asi que sale tambien unos
# 26 mm de ancho: cerca de un tercio de los 80 mm del rollo.
ALTO_LOGO_TIQUE = 26 * mm

# La linea de guiones que separa bloques. Es la del papel original: no es un
# filete, son guiones, y se dibuja con texto para que se corte donde se corte
# el rollo siga leyendose igual.
#
# El numero de pares esta contado para que quepa en un renglon: con mas, el
# ultimo par pasaba a una segunda linea y el separador salia con un muñon
# debajo.
GUIONES = "- " * 55


def _estilos_tique():
    """Los cuerpos del tique, mas pequenos que los de la media hoja.

    No heredan de `_estilos()`: ahi los tamanos estan pensados para un papel
    que se lee a un brazo de distancia sobre el mostrador, y el tique se lee
    en la mano. Compartirlos habria atado dos formatos que no tienen por que
    moverse juntos.
    """
    base = getSampleStyleSheet()
    normal = base["Normal"]

    def estilo(nombre, size, leading, **extra):
        return ParagraphStyle(
            nombre, parent=normal, fontSize=size, leading=leading, **extra
        )

    # Los cuerpos salen medidos del papel de referencia, no elegidos: el
    # tique se compara con el del sistema que se reemplaza puesto al lado, y
    # una escala propia -aunque fuera legible- se nota en cuanto los dos estan
    # sobre el mostrador. Tres escalones y nada mas: identidad del emisor,
    # cuerpo del documento y letra pequeña legal.
    return {
        "empresa": estilo(
            "t_empresa", 8, 9.6, fontName="Helvetica-Bold", alignment=1
        ),
        "empresa_pie": estilo("t_empresa_pie", 6.2, 7.6, alignment=1),
        # El RUC es la linea mas grande del papel despues del logotipo: es el
        # dato por el que se identifica al emisor ante SUNAT.
        "ruc": estilo("t_ruc", 11, 13.5, fontName="Helvetica-Bold", alignment=1),
        "titulo": estilo(
            "t_titulo", 10, 12.5, fontName="Helvetica-Bold", alignment=1
        ),
        "numero": estilo(
            "t_numero", 10, 12.5, fontName="Helvetica-Bold", alignment=1
        ),
        "etiqueta": estilo("t_etiqueta", 7.5, 9.4, fontName="Helvetica-Bold"),
        "dato": estilo("t_dato", 7.5, 9.4),
        "th": estilo("t_th", 7.5, 9.4, fontName="Helvetica-Bold"),
        "th_num": estilo(
            "t_th_num", 7.5, 9.4, fontName="Helvetica-Bold", alignment=2
        ),
        "celda": estilo("t_celda", 7, 8.8),
        "num": estilo("t_num", 7, 8.8, alignment=2),
        "guiones": estilo("t_guiones", 5.5, 6),
        "letras": estilo("t_letras", 7.5, 9.4, fontName="Helvetica-Bold"),
        "legal": estilo("t_legal", 5.4, 6.6, alignment=1),
        "resumen": estilo(
            "t_resumen", 5.4, 6.6,
            alignment=1,
            textColor=colors.HexColor("#3b6ea5"),
        ),
        "anulado": estilo(
            "t_anulado", 9, 11,
            fontName="Helvetica-Bold",
            alignment=1,
            textColor=colors.HexColor("#a52f22"),
        ),
    }


def _sin_relleno(tabla, extra=()):
    """Tabla sin bordes ni aire lateral, que es como se apilan las del tique."""
    tabla.setStyle(
        TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0.8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            *extra,
        ])
    )

    return tabla


def _guiones_tique(estilos):
    return Paragraph(GUIONES, estilos["guiones"])


def _cabecera_tique(receipt, estilos, ancho):
    """Logotipo, razon social, direcciones, telefono y RUC. Todo centrado."""
    sequence = receipt.sequence
    issuer = sequence.issuer

    piezas = []

    # El logotipo ocupa cerca de un tercio del ancho del rollo, como en el
    # papel de referencia. A 11 mm se quedaba en una marca de agua arriba del
    # todo: en un tique de 80 mm es lo primero que identifica de quien es el
    # papel, y a esa escala habia que acercarselo a los ojos para verlo.
    logo = _logo(ALTO_LOGO_TIQUE)

    # `_logo` devuelve una cadena vacía cuando no hay dibujo que poner, no
    # None: comparar contra None dejaba pasar esa cadena y el tique reventaba
    # al pedirle alineación a un texto. Un despliegue sin el archivo tiene que
    # poder entregar el papel igual.
    if logo:
        logo.hAlign = "CENTER"
        piezas.append(logo)
        piezas.append(Spacer(1, 1.5 * mm))

    if issuer:
        piezas.append(Paragraph(issuer.business_name, estilos["empresa"]))

        # Las direcciones son varios renglones de la cabecera, no varios
        # domicilios: vienen en un campo separadas por salto de linea y se
        # pintan una debajo de otra, como en el papel.
        for renglon in (issuer.address or "").splitlines():
            if renglon.strip():
                piezas.append(Paragraph(renglon.strip(), estilos["empresa_pie"]))

        if issuer.phone:
            piezas.append(
                Paragraph(f"Teléfono {issuer.phone}", estilos["empresa_pie"])
            )

        piezas.append(Spacer(1, 1.5 * mm))
        piezas.append(Paragraph(f"RUC {issuer.ruc}", estilos["ruc"]))

    piezas.append(Spacer(1, 2 * mm))
    piezas.append(Paragraph(sequence.document_title, estilos["titulo"]))
    piezas.append(
        Paragraph(
            f"{receipt.series}-{format_receipt_number(receipt.number)}",
            estilos["numero"],
        )
    )

    return piezas


def _abonado_tique(receipt, estilos, ancho):
    """Filas etiqueta / valor con a quien se le cobro."""
    payment = receipt.payment
    customer = payment.customer
    direccion = customer.addresses.filter(is_primary=True).first()

    etiqueta = 21 * mm
    filas = [
        [
            Paragraph("F. EMISIÓN", estilos["etiqueta"]),
            Paragraph(
                receipt.issued_at.strftime("%d/%m/%Y"), estilos["dato"]
            ),
        ],
        [
            Paragraph("CÓDIGO", estilos["etiqueta"]),
            # El codigo del abonado y su documento comparten renglon, como en
            # el papel: son las dos maneras de nombrarlo y se leen juntas.
            _sin_relleno(Table(
                [[
                    Paragraph(customer.code, estilos["dato"]),
                    Paragraph(
                        customer.get_document_type_display().upper(),
                        estilos["etiqueta"],
                    ),
                    Paragraph(customer.document_number, estilos["dato"]),
                ]],
                colWidths=[22 * mm, 11 * mm, None],
            )),
        ],
        [
            Paragraph("ABONADO", estilos["etiqueta"]),
            Paragraph(str(customer).upper(), estilos["dato"]),
        ],
        [
            Paragraph("DIRECCIÓN", estilos["etiqueta"]),
            Paragraph(
                (direccion.address if direccion else "").upper(),
                estilos["dato"],
            ),
        ],
        [
            Paragraph("MONEDA", estilos["etiqueta"]),
            Paragraph("SOLES", estilos["dato"]),
        ],
    ]

    return _sin_relleno(
        Table(filas, colWidths=[etiqueta, ancho - etiqueta])
    )


def _detalle_tique(receipt, estilos, ancho, lines):
    """El detalle, con la cantidad delante de la descripcion.

    La cantidad va entre corchetes pegada al concepto y no en columna propia:
    en 80 mm una columna para «1.00000» se come el ancho que necesita la
    descripcion, que es lo que el abonado lee para reconocer su mes.
    """
    pu = 16 * mm
    total = 14 * mm

    filas = [[
        Paragraph("DESCRIPCIÓN", estilos["th"]),
        Paragraph("P/U", estilos["th_num"]),
        Paragraph("TOTAL", estilos["th_num"]),
    ]]

    for linea in lines:
        filas.append([
            Paragraph(
                f"[{linea['quantity']:.5f}] {linea['description']}",
                estilos["celda"],
            ),
            Paragraph(f"{linea['unit_price']:.6f}", estilos["num"]),
            Paragraph(f"{linea['total']:.2f}", estilos["num"]),
        ])

    return _sin_relleno(
        Table(filas, colWidths=[ancho - pu - total, pu, total]),
        extra=[("BOTTOMPADDING", (0, 0), (-1, 0), 2.2)],
    )


def _importes_tique(estilos, ancho, totals):
    """El recuadro de importes: columna de concepto, «S/» y cifra."""
    moneda = 8 * mm
    cifra = 18 * mm

    filas = [
        ("OP. GRAVADA", totals["gravada"], False),
        ("OP. EXONERADA", totals["exonerada"], False),
        ("DESCUENTOS", totals["discount"], False),
        (f"I.G.V. {IGV_RATE:.0%}", totals["igv"], False),
        ("TOTAL", totals["total"], True),
    ]

    datos = []

    for concepto, importe, fuerte in filas:
        estilo_texto = estilos["etiqueta"] if fuerte else estilos["dato"]
        estilo_cifra = estilos["letras"] if fuerte else estilos["num"]

        datos.append([
            Paragraph(concepto, estilo_texto),
            Paragraph("S/", estilos["dato"]),
            Paragraph(
                f"{importe:.2f}",
                estilo_cifra if fuerte else estilos["num"],
            ),
        ])

    return _sin_relleno(
        Table(datos, colWidths=[ancho - moneda - cifra, moneda, cifra]),
        extra=[("ALIGN", (2, 0), (2, -1), "RIGHT")],
    )


def _pie_tique(receipt, estilos, ancho, totals):
    """Importe en letras, condicion de pago, QR y leyenda legal."""
    piezas = [
        Paragraph(amount_in_words(totals["total"]), estilos["letras"]),
        Spacer(1, 1.5 * mm),
        Paragraph(
            f"CONDICIÓN DE PAGO   {payment_condition(receipt.payment)}",
            estilos["etiqueta"],
        ),
        Spacer(1, 2 * mm),
    ]

    codigo = _qr(receipt, totals, 30 * mm)
    codigo.hAlign = "CENTER"
    piezas.append(codigo)

    piezas.append(Paragraph(_resumen(receipt, totals), estilos["resumen"]))
    piezas.append(
        Paragraph(
            "Representación impresa de "
            f"{receipt.sequence.document_title}, verifique su "
            "comprobante en www.sunat.gob.pe",
            estilos["legal"],
        )
    )

    return piezas


def _render_ticket(receipt, buffer, lines, totals):
    """El tique de boleta, tan largo como lo que tiene que decir.

    Se arma dos veces: la primera para medir cuanto ocupa la historia, la
    segunda ya sobre una pagina de ese alto. Un tique de rollo no tiene alto
    fijo, y darle uno dejaria media cuarta en blanco en un cobro de una linea.
    """
    estilos = _estilos_tique()
    ancho = ANCHO_TIQUE - 2 * MARGEN_TIQUE

    historia = []

    if receipt.is_voided:
        historia.append(
            Paragraph(
                f"ANULADO — {receipt.payment.void_reason}", estilos["anulado"]
            )
        )
        historia.append(Spacer(1, 2 * mm))

    historia.extend(_cabecera_tique(receipt, estilos, ancho))
    historia.append(Spacer(1, 2.5 * mm))
    historia.append(_abonado_tique(receipt, estilos, ancho))
    historia.append(_guiones_tique(estilos))
    historia.append(_detalle_tique(receipt, estilos, ancho, lines))
    historia.append(_guiones_tique(estilos))
    historia.append(_importes_tique(estilos, ancho, totals))
    historia.append(Spacer(1, 1.5 * mm))
    historia.extend(_pie_tique(receipt, estilos, ancho, totals))

    alto = sum(
        pieza.wrap(ancho, ALTO_TIQUE_MINIMO * 4)[1] for pieza in historia
    )
    alto = max(ALTO_TIQUE_MINIMO, alto + 2 * MARGEN_TIQUE + COLA_TIQUE)

    documento = SimpleDocTemplate(
        buffer,
        pagesize=(ANCHO_TIQUE, alto),
        leftMargin=MARGEN_TIQUE,
        rightMargin=MARGEN_TIQUE,
        topMargin=MARGEN_TIQUE,
        bottomMargin=MARGEN_TIQUE,
        title=receipt.full_number,
        author=str(receipt.sequence.issuer or "SICV"),
    )
    documento.build(historia)

    return f"{receipt.full_number}.pdf"


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


def _sin_margen_blanco(ruta):
    """El archivo sin el aire en blanco que lo rodea, o el archivo tal cual.

    El logotipo que se deja en MEDIA_ROOT viene con margen dentro de la propia
    imagen -el de hoy, un 13% arriba y un 19% abajo-, y ese margen es parte del
    dibujo: al colocarlo alineado con la parte de arriba de su celda, lo que se
    ve arranca tres milímetros por debajo de la razón social que tiene al lado
    y el logotipo parece caído.

    Se recorta al dibujar y no en el archivo. El logotipo lo deja alguien en su
    sitio, no viene con el código, así que no es nuestro para reescribirlo; y un
    recorte al vuelo sigue valiendo cuando lo cambien por otro con distinto
    aire, que es lo que va a pasar.

    Si no se puede recortar se devuelve el archivo sin tocar: un logotipo un
    poco caído es mejor que una ventanilla que no puede entregar el papel.
    """
    try:
        from PIL import Image as PilImage, ImageChops
    except Exception:
        return str(ruta)

    try:
        original = PilImage.open(ruta).convert("RGB")
        blanco = PilImage.new("RGB", original.size, (255, 255, 255))
        mascara = (
            ImageChops.difference(original, blanco)
            .convert("L")
            .point(lambda valor: 255 if valor > UMBRAL_BLANCO else 0)
        )
        caja = mascara.getbbox()
    except Exception:
        return str(ruta)

    # Sin caja el dibujo es todo blanco; recortarlo lo dejaría en nada.
    if caja is None:
        return str(ruta)

    # Como archivo en memoria y no como imagen de PIL: `platypus.Image` espera
    # una ruta o algo que se pueda abrir, y una imagen de PIL la rechaza.
    recortado = BytesIO()
    original.crop(caja).save(recortado, format="PNG")
    recortado.seek(0)

    return recortado


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
        imagen = Image(_sin_margen_blanco(ruta))
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
        [[_logo(ALTO_LOGO_HOJA), identidad, recuadro]],
        colWidths=[
            COLUMNA_LOGO_HOJA,
            ancho - COLUMNA_LOGO_HOJA - 68 * mm,
            68 * mm,
        ],
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


def _es_factura(receipt):
    """Si este papel es una factura.

    La factura lleva cuatro cosas que el recibo y la boleta no -condición de
    pago, guía de remisión, detracción y el cuadro de cuotas-, y se pregunta
    desde tres sitios distintos del dibujo. Se responde por el código de
    SUNAT del talonario y no por la letra de la serie: `F002` y `F002-CLA`
    son dos blocks de la misma serie impresa, y mañana puede haber una
    factura que no empiece por F.
    """
    return receipt.sequence.sunat_code == ReceiptSequence.SunatCode.FACTURA


def _abonado(receipt, estilos, ancho):
    """La caja del abonado: a quién se le cobró y cuándo.

    La columna de la derecha crece en la factura: lleva además la condición
    de pago y la guía de remisión, que es como las emite el sistema que se
    reemplaza. En el recibo y en la boleta esas dos filas no existen -no
    estarían en blanco, no estarían-.
    """
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

    filas_derecha = [
        par("F. Emisión", receipt.issued_at.strftime("%d/%m/%Y %H:%M:%S")),
        par("Moneda", "SOLES"),
    ]

    if _es_factura(receipt):
        filas_derecha.append(
            par("Condición de pago", payment_condition(payment))
        )
        # En blanco: el sistema no emite guías de remisión. La fila va igual
        # porque el formato la tiene, y un hueco con su etiqueta se lee como
        # «no aplica»; la fila ausente, en cambio, haría que dos facturas de
        # la misma empresa no tuvieran la misma forma.
        filas_derecha.append(par("G. Remisión", ""))

    derecha = Table(
        filas_derecha,
        colWidths=[26 * mm, 26 * mm],
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

    Diez campos separados por `|`, en el orden exacto de un comprobante
    declarado. Está comprobado contra uno: se escaneó el QR de la boleta
    B003-0034430 de INVERSIONES -aceptada por SUNAT- y devolvió

        20603110456|03|B003|0034430|9.15|60.00|2025-12-22|1|20723004|R5Betfw/…

    Los dos campos que antes iban en castellano -«BOLETA DE VENTA
    ELECTRÓNICA» y «DNI»- resultaron ser códigos de catálogo, `03` y `1`, y el
    décimo campo, que faltaba, es el valor resumen que ya se imprime debajo.

    Sigue sin ser un comprobante declarado: el valor resumen es el de
    `_resumen`, calculado sobre los datos del propio recibo, y no el hash del
    XML firmado. Lo que esto fija es la forma, para que el día que se declare
    solo cambie ese último campo.
    """
    issuer = receipt.sequence.issuer
    customer = receipt.payment.customer

    contenido = "|".join([
        issuer.ruc if issuer else "",
        receipt.sequence.sunat_code,
        receipt.series,
        format_receipt_number(receipt.number),
        f"{totals['igv']:.2f}",
        f"{totals['total']:.2f}",
        receipt.issued_at.strftime("%Y-%m-%d"),
        sunat_receiver_document(customer.document_type),
        customer.document_number,
        _resumen(receipt, totals),
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
        Paragraph(_leyenda(receipt), estilos["pie"]),
    ]

    filas = [
        ("Op. Gravada", f"S/{totals['gravada']:.2f}"),
        ("Op. Exonerada", f"S/{totals['exonerada']:.2f}"),
        ("Op. Inafecta", f"S/{totals['inafecta']:.2f}"),
        ("Op. Gratuita", f"S/{totals['gratuita']:.2f}"),
        ("Total Dscto", f"S/{totals['discount']:.2f}"),
        ("I.G.V.", f"S/{totals['igv']:.2f}"),
        ("Importe Total", f"S/{totals['total']:.2f}"),
    ]

    if _es_factura(receipt):
        # Sin importe, como en el papel original. El sistema no liquida
        # detracciones, y escribir «S/0.00» donde no hay operación afirmaría
        # que se calculó y dio cero. El hueco dice que no aplica.
        #
        # Total Neto es lo que queda tras la detracción; sin ella sería el
        # importe total otra vez, repetido un renglón más abajo.
        filas.extend([("Detracción", ""), ("Total Neto", "")])

    importes = Table(
        [
            [Paragraph(etiqueta, estilos["pie"]),
             Paragraph(valor, estilos["num"])]
            for etiqueta, valor in filas
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


def _leyenda(receipt):
    """La línea legal del pie.

    La factura invita a comprobarla en SUNAT y el recibo no: es lo que
    imprime cada uno en el sistema que se reemplaza, donde los dos están
    declarados de verdad. Aquí todavía no lo están -no hay XML firmado ni
    envío-, así que esa invitación promete una consulta que hoy devolvería
    que el comprobante no existe. Se reproduce el formato porque es el
    encargo; que la promesa se sostenga depende de que se declare, no de
    esta línea.
    """
    leyenda = f"Representación impresa de {receipt.sequence.document_title}"

    if _es_factura(receipt):
        return f"{leyenda}, verifique su comprobante en www.sunat.gob.pe"

    return leyenda


# Cuantas cuotas caben de ancho en la hoja. El papel original las reparte en
# tres columnas de «Nº Cuota / F. Venc. / Monto», y con una sola cuota deja
# las otras dos vacías en vez de estirar la primera.
CUOTAS_POR_FILA = 3


def _cuotas(receipt, estilos, ancho, totals):
    """El cuadro de cuotas del pie, o None si no lo lleva.

    Solo la factura al crédito: al contado no hay nada que vencer, y el papel
    original no dibuja el cuadro. Hoy siempre es **una** cuota -la fecha de
    vencimiento del comprobante por su importe entero-, que es como emite el
    sistema que se reemplaza. El día que una factura se pacte en varias, las
    cuotas serán filas propias y esto leerá de ellas en vez de derivarlas.

    El pendiente es el total y no el saldo de hoy: el papel dice lo que se
    debía al emitirlo, no lo que se deba cuando alguien lo reimprima. Si
    cambiara al pagarse, dos copias del mismo comprobante dirían cifras
    distintas.
    """
    payment = receipt.payment

    if not _es_factura(receipt) or payment_condition(payment) != "CREDITO":
        return None

    cuotas = [(1, payment.due_date, totals["total"])]

    grupo = ancho / CUOTAS_POR_FILA
    anchos = [grupo * 0.28, grupo * 0.34, grupo * 0.38] * CUOTAS_POR_FILA

    cabecera = []
    for _ in range(CUOTAS_POR_FILA):
        cabecera.extend([
            Paragraph("Nº Cuota", estilos["etiqueta"]),
            Paragraph("F. Venc.", estilos["etiqueta"]),
            Paragraph("Monto", estilos["etiqueta"]),
        ])

    filas = []
    for inicio in range(0, len(cuotas), CUOTAS_POR_FILA):
        fila = []
        for numero, vence, monto in cuotas[inicio:inicio + CUOTAS_POR_FILA]:
            fila.extend([
                Paragraph(str(numero), estilos["pie"]),
                Paragraph(
                    vence.strftime("%d/%m/%Y") if vence else "", estilos["pie"]
                ),
                Paragraph(f"{monto:.2f}", estilos["pie"]),
            ])
        fila.extend([""] * (3 * CUOTAS_POR_FILA - len(fila)))
        filas.append(fila)

    resumen = [
        Paragraph(
            f"Monto neto pendiente de pago: S/{totals['total']:.2f}",
            estilos["etiqueta"],
        ),
        "",
        "",
        Paragraph(f"Total de cuotas: {len(cuotas)}", estilos["etiqueta"]),
    ] + [""] * (3 * CUOTAS_POR_FILA - 4)

    tabla = Table([resumen, cabecera] + filas, colWidths=anchos)
    tabla.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("SPAN", (0, 0), (2, 0)),
            ("SPAN", (3, 0), (5, 0)),
            ("LINEABOVE", (0, 0), (-1, 0), 1.1, LINEA),
            ("LINEBELOW", (0, 1), (-1, 1), 0.6, LINEA),
            ("TOPPADDING", (0, 0), (-1, -1), 1.4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.4),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ])
    )

    return tabla


def render_receipt(receipt, buffer):
    """Escribe el comprobante en `buffer` y devuelve el nombre del archivo.

    El nombre es el número completo -«B001-0041314.pdf»-, que es como el
    operador lo va a buscar en su carpeta de descargas: el mismo texto que lee
    en la pantalla y en el papel.
    """
    lines = receipt_lines(receipt)
    totals = receipt_totals(receipt, lines)

    # En que papel sale lo dice el talonario, como ya decia quien emite y con
    # que numero. Deducirlo aqui de la serie -«empieza por B»- pondria la
    # regla en el dibujo, y los blocks de un cobrador, que tambien son
    # boletas, acabarian en el papel equivocado.
    if receipt.sequence.print_format == ReceiptSequence.PrintFormat.TICKET:
        return _render_ticket(receipt, buffer, lines, totals)

    estilos = _estilos()

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
    cuotas = _cuotas(receipt, estilos, ancho, totals)
    separadores = [3.5 * mm, 3 * mm, 3 * mm]

    # El cuadro de cuotas cuelga del pie y va pegado a el: es su continuacion,
    # no otro bloque. Cuenta para el hueco que se reparte, o el estiron del
    # detalle lo empujaria a una segunda hoja.
    cola = [pie] if cuotas is None else [pie, Spacer(1, 2 * mm), cuotas]

    # El detalle se arma dos veces: la primera para saber cuánto ocupa por sí
    # solo, la segunda ya con el hueco que sobra metido en su fila vacía. Sin
    # esta cuenta, el pie quedaba a media hoja y el cuarto de abajo en blanco,
    # que es lo que distingue un comprobante de un borrador.
    detalle = _detalle(receipt, estilos, ancho, lines)

    ocupado = sum(separadores) + sum(
        pieza.wrap(ancho, documento.height)[1]
        for pieza in encabezado + [cabecera, abonado, detalle] + cola
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
        ]
        + cola
    )

    return f"{receipt.full_number}.pdf"
