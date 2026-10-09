"""Read-only adapter for the observed 40-column SUNAT RVIE export.

Unknown schemas and grouped ranges fail closed; no tax or status is inferred.
ZIP members are read in memory and never extracted onto disk.
"""
import csv
import stat
from collections import Counter
from io import BytesIO, StringIO
from pathlib import PurePosixPath
from zipfile import ZipFile

from django.core.exceptions import ValidationError

from . import importers

NATIVE_HEADERS = [
    "Ruc", "Razon Social", "Periodo", "CAR SUNAT", "Fecha de emisión", "Fecha Vcto/Pago",
    "Tipo CP/Doc.", "Serie del CDP", "Nro CP o Doc. Nro Inicial (Rango)", "Nro Final (Rango)",
    "Tipo Doc Identidad", "Nro Doc Identidad", "Apellidos Nombres/ Razón Social",
    "Valor Facturado Exportación", "BI Gravada", "Dscto BI", "IGV / IPM", "Dscto IGV / IPM",
    "Mto Exonerado", "Mto Inafecto", "ISC", "BI Grav IVAP", "IVAP", "ICBPER", "Otros Tributos",
    "Total CP", "Moneda", "Tipo Cambio", "Fecha Emisión Doc Modificado", "Tipo CP Modificado",
    "Serie CP Modificado", "Nro CP Modificado", "ID Proyecto Operadores Atribución", "Tipo de Nota",
    "Est. Comp", "Valor FOB Embarcado", "Valor OP Gratuitas", "Tipo Operación", "DAM / CP", "CLU",
]
NATIVE_FORMAT = "SUNAT-RVIE-40"
MAX_EXPANDED_BYTES = 50 * 1024 * 1024


def read_zip(raw):
    with ZipFile(BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) != 1:
            raise ValidationError("El ZIP de SIRE debe contener un único CSV, sin archivos adicionales.")
        member = members[0]
        path = PurePosixPath(member.filename)
        if (member.is_dir() or path.is_absolute() or len(path.parts) != 1
                or "\\" in member.filename or ":" in member.filename
                or not member.filename.lower().endswith(".csv")
                or stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1):
            raise ValidationError("El ZIP contiene una ruta o un tipo de archivo no admitido.")
        if member.file_size > MAX_EXPANDED_BYTES:
            raise ValidationError("El CSV descomprimido supera 50 MB.")
        with archive.open(member) as stream:
            content = stream.read(MAX_EXPANDED_BYTES + 1)
        if len(content) > MAX_EXPANDED_BYTES:
            raise ValidationError("El CSV descomprimido supera 50 MB.")
        return content, importers.text_value(member.filename, 200)


def parse_native(decoded, delimiter, ruc, period):
    reader = csv.reader(StringIO(decoded), delimiter=delimiter, strict=True)
    headers = next(reader, [])
    if [importers.normalize(h) for h in headers] != [importers.normalize(h) for h in NATIVE_HEADERS]:
        raise ValidationError("Encabezados SIRE no reconocidos. Use el CSV RVIE de 40 columnas o la plantilla SICV.")
    docs, seen = [], set()
    states = Counter()
    for row_number, values in enumerate(reader, 2):
        if row_number > importers.MAX_ROWS + 1:
            raise ValidationError("El CSV supera 15,000 filas.")
        try:
            if len(values) != len(NATIVE_HEADERS):
                raise ValidationError("Cantidad de columnas incorrecta.")
            values = [importers.text_value(v, 1000) for v in values]
            if values[0] != ruc or values[2] != period.strftime("%Y%m"):
                raise ValidationError("RUC o periodo distinto al seleccionado.")
            if values[9]:
                raise ValidationError("Los comprobantes agrupados por rango requieren revisión; no se importan como uno solo.")
            key = importers.document_key(values[6], values[7], values[8])
            if key in seen:
                raise ValidationError("Comprobante repetido en el archivo SIRE.")
            seen.add(key)
            if values[26] not in ("PEN", "USD"):
                raise ValidationError("Moneda no admitida: use PEN o USD.")
            for index in [*range(13, 26), 35, 36]:
                importers.money(values[index], optional=index != 25)
            if values[27]:
                importers.money(values[27], places=5)
            for index in (5, 28):
                if values[index]:
                    importers.parsed_date(values[index])
            if any(values[index] for index in (29, 30, 31)):
                importers.document_key(values[29], values[30], values[31])
            state = importers.text_value(values[34], 60)
            states[state or "Sin dato"] += 1
            docs.append(dict(
                document_type=key[0], series=key[1], number=key[2],
                issue_date=importers.parsed_date(values[4]),
                receiver_document=importers.text_value(values[11], 20),
                receiver_name=importers.text_value(values[12], 250), currency=values[26],
                base=importers.money(values[14], optional=True), tax=importers.money(values[16], optional=True),
                total=importers.money(values[25]), local_state="", sunat_state="", sire_state=state,
                source_details={"format": NATIVE_FORMAT, "row": row_number, "fields": dict(zip(NATIVE_HEADERS, values))},
                flags=[] if state else ["NO_SIRE_STATE"],
            ))
        except ValidationError as error:
            raise ValidationError(f"CSV SIRE, fila {row_number}: {' '.join(error.messages)}") from None
    return docs, [], {
        "format": NATIVE_FORMAT, "state_counts": dict(states),
        "origin": "Exportación RVIE aportada por el usuario; sin consulta automática a SUNAT",
        "warnings": ["Est. Comp se conserva como código del archivo SIRE. No equivale a una constancia de aceptación.",
                     "Las fechas muestran la cobertura del archivo, no acreditan que el periodo esté completo."],
    }
