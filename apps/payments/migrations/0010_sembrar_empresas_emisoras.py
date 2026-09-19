"""Las razones sociales del grupo y a cuál pertenece cada talonario.

Quién emite el comprobante lo decide el talonario que el operador elige al
cobrar, igual que el correlativo: el block B001 imprime CABLE LOS ANDES y el
S010-SPEEDY imprime SPEEDY QUANTICO, sin que la pantalla tenga que preguntar
nada aparte.

Los RUC son de relleno y están marcados como tales: el papel real llevará los
verdaderos, y dejarlos en blanco habría dado un comprobante sin recuadro donde
no se ve que falta el dato. Lo mismo la dirección y el teléfono, que hoy son
los de la oficina de Jauja para las tres.
"""

from django.db import migrations


# código, razón social, RUC de relleno
EMPRESAS = [
    ("CLA", "CABLE LOS ANDES E.I.R.L.", "20000000001"),
    ("INV", "INVERSIONES E.I.R.L.", "20000000002"),
    ("SPQ", "SPEEDY QUANTICO E.I.R.L.", "20000000003"),
]

DIRECCION = "Av. Huancayo Nº215 - Jauja"
TELEFONO = "064 466080"

# Qué talonario imprime qué razón social, y cómo se titula su documento.
#
# El prefijo de la etiqueta ya lo decía en el sistema anterior: «B:» es una
# boleta, «F:» una factura y los demás recibos de servicio público. Se guarda
# por talonario en vez de deducirse del prefijo cada vez que se imprime,
# porque un block puede cambiar de tipo sin cambiar de nombre.
TALONARIOS = [
    # código del talonario, código de empresa, título del documento
    ("JU1", "CLA", "BOLETA DE VENTA ELECTRÓNICA"),
    ("JU2", "CLA", "BOLETA DE VENTA ELECTRÓNICA"),
    ("JU3", "CLA", "BOLETA DE VENTA ELECTRÓNICA"),
    ("MR3", "CLA", "BOLETA DE VENTA ELECTRÓNICA"),
    ("MR4", "CLA", "BOLETA DE VENTA ELECTRÓNICA"),
    ("ST1", "CLA", "BOLETA DE VENTA ELECTRÓNICA"),
    ("ST2", "CLA", "BOLETA DE VENTA ELECTRÓNICA"),
    ("ST3", "CLA", "BOLETA DE VENTA ELECTRÓNICA"),
    ("ST4", "CLA", "BOLETA DE VENTA ELECTRÓNICA"),
    ("ST5", "CLA", "BOLETA DE VENTA ELECTRÓNICA"),
    ("B001", "CLA", "BOLETA DE VENTA ELECTRÓNICA"),
    ("B002", "INV", "BOLETA DE VENTA ELECTRÓNICA"),
    ("F001", "CLA", "FACTURA ELECTRÓNICA"),
    ("F002", "INV", "FACTURA ELECTRÓNICA"),
    ("S010-VELOCIDAD", "SPQ", "RECIBO DE SERVICIO PÚBLICO ELECTRÓNICO"),
    ("S010-RED-OPTICA", "SPQ", "RECIBO DE SERVICIO PÚBLICO ELECTRÓNICO"),
    ("S010-SPEEDY", "SPQ", "RECIBO DE SERVICIO PÚBLICO ELECTRÓNICO"),
    ("VCOND", "CLA", "RECIBO DE SERVICIO PÚBLICO ELECTRÓNICO"),
    # El talonario propio del sistema, retirado de la ventanilla pero con
    # comprobantes ya emitidos que tienen que poder seguir imprimiéndose.
    ("R001", "CLA", "RECIBO DE SERVICIO PÚBLICO ELECTRÓNICO"),
]


def sembrar(apps, schema_editor):
    Issuer = apps.get_model("payments", "Issuer")
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")

    empresas = {}

    for code, business_name, ruc in EMPRESAS:
        empresa, _ = Issuer.objects.update_or_create(
            code=code,
            defaults={
                "business_name": business_name,
                "ruc": ruc,
                "address": DIRECCION,
                "phone": TELEFONO,
            },
        )
        empresas[code] = empresa

    for code, empresa, titulo in TALONARIOS:
        ReceiptSequence.objects.filter(code=code).update(
            issuer=empresas[empresa],
            document_title=titulo,
        )


def deshacer(apps, schema_editor):
    Issuer = apps.get_model("payments", "Issuer")
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")

    ReceiptSequence.objects.update(issuer=None)
    Issuer.objects.filter(code__in=[code for code, _, _ in EMPRESAS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0009_issuer_receiptsequence_document_title_and_more"),
    ]

    operations = [
        migrations.RunPython(sembrar, deshacer),
    ]
