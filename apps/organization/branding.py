"""Las imágenes de la empresa que salen impresas en sus papeles.

El logotipo -que llevan el comprobante de cobranza y el contrato de abonado-
y la firma con la que la empresa suscribe sus contratos. Dónde viven los
archivos y cómo se preparan para el papel se decide **una vez y aquí**: si
cada módulo los buscara por su cuenta, cambiar el logotipo obligaría a
acordarse de todos los sitios, y el que se olvidara seguiría imprimiendo el
anterior.

Vive en `organization` porque son de la empresa, no de cobranza ni de
contratos: los dos son consumidores, ninguno es su dueño.

Los archivos se dejan en MEDIA_ROOT y no vienen con el código: los pone
administración y los cambia sin pasar por un despliegue. Es provisional a
propósito -está pendiente decidir si cada razón social lleva los suyos, y
entonces serán campos del emisor y no rutas fijas-, así que la carpeta se
declara en un solo sitio.
"""

from io import BytesIO
from pathlib import Path

from django.conf import settings


# La marca tiene dos dibujos y no son intercambiables:
#
# - el **isotipo**, casi cuadrado, para donde hay una columna estrecha y
#   mucho alto -la cabecera del comprobante de cobranza-;
# - el **logotipo apaisado**, con la marca y el lema en una línea, para una
#   franja ancha y baja, como la cabecera del contrato.
#
# Estirar uno al hueco del otro lo deja diminuto o desbordado, así que cada
# papel pide el suyo por su nombre. Los nombres son los de los archivos que
# entregó administración; si mañana los cambian, se cambian aquí.
STEM = "telecable-logo"
STEM_APAISADO = "Logo-telecable-2"

# La firma con la que una razón social suscribe sus contratos, una por código
# de empresa emisora -el mismo que usa cobranza-. El día que otra firme, basta
# con dejar su archivo al lado.
#
# Tiene que ser **PNG con fondo transparente y recortado**: el sello se apoya
# sobre la línea de firma del contrato, y un JPEG con su fondo blanco taparía
# la línea y dejaría el recuadro del recorte a la vista.
STEM_FIRMA = "firma_"


def stem_de_la_firma(codigo_de_empresa):
    """El nombre que tiene que llevar el archivo de firma de esa empresa."""

    return f"{STEM_FIRMA}{codigo_de_empresa}"

# Cualquier extensión, y cualquier cosa pegada detrás del nombre. El archivo
# llega descargado de un navegador o de un chat, que le añaden lo suyo
# -«telecable-logo.jpg.jpeg» es lo que salió la primera vez-, y el fallo es
# mudo: el papel se imprime igual y sin logo. Exigir el nombre exacto costaba
# una vuelta entera para descubrir que sobraba una extensión.
PATRON = f"{STEM}*"

# Con varios candidatos gana el primero de esta lista. Un PNG antes que un
# JPG porque conserva la transparencia, que en una cabecera se nota.
SUFIJOS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# Cuánto se puede apartar un píxel del blanco para seguir siendo margen.
#
# Un umbral y no igualdad exacta: el archivo de hoy es un JPEG, y un JPEG no
# guarda el blanco exacto -lo deja en 250 y pico-, así que comparar a pelo no
# recortaría nada. Bajo, para no comerse un trazo claro del dibujo.
UMBRAL_BLANCO = 18


def directorio_de_las_imagenes():
    """Dónde se busca. Se lee al llamar para que las pruebas puedan moverlo."""

    return Path(settings.MEDIA_ROOT)


def buscar_imagen(stem, directorio=None):
    """El archivo que empieza por `stem`, o `None` si no hay ninguno.

    Sirve para cualquier imagen de la empresa -el logotipo, la firma- porque
    el problema es el mismo: el archivo lo deja una persona, con la extensión
    que le tocó y las mayúsculas que le tocaron.

    Con varios candidatos gana el de mejor extensión y, a igualdad, el de
    nombre más corto: entre «telecable-logo.png» y «telecable-logo (1).png»
    se queda con el limpio, que es el que alguien puso a propósito.

    El nombre se compara **sin distinguir mayúsculas**. Windows tampoco las
    distingue y el servidor sí: un archivo guardado como «Logo-...» dejaría
    el papel bien en el portátil de quien lo prueba y sin logotipo en
    producción, que es el peor sitio donde descubrirlo.
    """

    carpeta = (
        Path(directorio) if directorio is not None else directorio_de_las_imagenes()
    )

    if not carpeta.exists():
        return None

    principio = stem.lower()

    candidatos = [
        ruta
        for ruta in carpeta.iterdir()
        if ruta.is_file() and ruta.name.lower().startswith(principio)
    ]

    if not candidatos:
        return None

    def preferencia(ruta):
        suffix = ruta.suffix.lower()
        puesto = SUFIJOS.index(suffix) if suffix in SUFIJOS else len(SUFIJOS)

        return (puesto, len(ruta.name), ruta.name)

    return sorted(candidatos, key=preferencia)[0]


def buscar_logo(directorio=None, stem=STEM):
    """El archivo del logotipo pedido, o `None` si no hay ninguno.

    `stem` elige el dibujo: el isotipo por defecto, `STEM_APAISADO` para la
    versión en línea.
    """

    return buscar_imagen(stem, directorio)


def logo_sin_margen(ruta, umbral=UMBRAL_BLANCO):
    """El archivo sin el aire en blanco que lo rodea, o el archivo tal cual.

    El logotipo trae margen dentro de la propia imagen, y ese margen es parte
    del dibujo: colocado junto a un texto, lo que se ve arranca varios
    milímetros más abajo y el logotipo parece caído.

    Se recorta al dibujar y no en el archivo. El logotipo lo deja alguien en
    su sitio, no viene con el código, así que no es nuestro para reescribirlo;
    y un recorte al vuelo sigue valiendo cuando lo cambien por otro con
    distinto aire, que es lo que va a pasar.

    Si no se puede recortar se devuelve el archivo sin tocar: un logotipo un
    poco caído es mejor que un papel que no se puede entregar.
    """

    try:
        from PIL import Image, ImageChops
    except Exception:
        return str(ruta)

    try:
        original = Image.open(ruta).convert("RGB")
        blanco = Image.new("RGB", original.size, (255, 255, 255))
        mascara = (
            ImageChops.difference(original, blanco)
            .convert("L")
            .point(lambda valor: 255 if valor > umbral else 0)
        )
        caja = mascara.getbbox()
    except Exception:
        return str(ruta)

    # Sin caja el dibujo es todo blanco; recortarlo lo dejaría en nada.
    if caja is None:
        return str(ruta)

    # Como archivo en memoria y no como imagen de PIL: los renderizadores de
    # PDF esperan una ruta o algo que se pueda abrir, y una imagen de PIL la
    # rechazan.
    recortado = BytesIO()
    original.crop(caja).save(recortado, format="PNG")
    recortado.seek(0)

    return recortado
