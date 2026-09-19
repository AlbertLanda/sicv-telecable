"""Lee el texto dibujado en un PDF, para poder afirmar algo sobre él.

Existe porque el PDF era el único de los cuatro formatos cuyo contenido no se
podía comprobar: las pruebas confirmaban que el archivo empezaba por `%PDF` y
ahí se quedaban. Con eso, quitar una columna de la hoja impresa -o dejarle un
subtítulo que ya no debía estar- pasaba la suite sin que nada se quejara.

No pretende ser un extractor de PDF completo. Solo deshace lo que reportlab
encadena -ASCII85 y luego Flate- y devuelve las cadenas que el documento pinta,
en el orden en que las pinta.
"""

import base64
import re
import zlib


def _descomprimir(bruto):
    """Deshace los filtros de un flujo de reportlab."""
    candidatos = [bruto]

    limpio = bruto.strip()
    if limpio.endswith(b"~>"):
        limpio = limpio[:-2]

    try:
        candidatos.append(base64.a85decode(limpio, adobe=False))
    except Exception:
        pass

    for candidato in candidatos:
        try:
            return zlib.decompress(candidato)
        except zlib.error:
            continue

    return b""


def pdf_strings(datos):
    """Las cadenas de texto del PDF, en orden de dibujo."""
    flujos = []

    for marca in re.finditer(rb"stream", datos):
        inicio = marca.end()
        while datos[inicio:inicio + 1] in (b"\r", b"\n"):
            inicio += 1

        fin = datos.find(b"endstream", inicio)
        flujos.append(_descomprimir(datos[inicio:fin]))

    crudo = b"\n".join(flujos).decode("latin-1")

    # El octal de las tildes se deshace aquí -«Emisi\363n» vuelve a ser
    # «Emisión»- para que las pruebas puedan escribir las etiquetas como se
    # leen y no como las codifica el formato.
    cadenas = re.findall(r"\(([^()]*)\)\s*Tj", crudo)

    return [
        re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), cadena)
        for cadena in cadenas
    ]


def pdf_text(datos):
    """Todo el texto del PDF en una sola cadena."""
    return " ".join(pdf_strings(datos))
