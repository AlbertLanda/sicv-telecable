"""Las boletas B00x se imprimen en tique, y INVERSIONES gana sus datos reales.

Dos cosas que van juntas porque salen de la misma boleta de muestra.

**El formato.** Los blocks de boleta numerados (B001 a B007) se entregan en un
tique estrecho en vertical, no en la media hoja apaisada: cabecera centrada con
el logotipo, los datos del abonado en filas etiqueta/valor, el detalle entre
líneas de guiones y abajo el recuadro de importes, el importe en letras, el QR
y la leyenda de representación impresa.

Los blocks de un cobrador (`JU*`, `MR*`, `ST*`) **también son boletas y no
entran**: se quedan en media hoja. Por eso el formato es un campo del talonario
y no se deduce de la letra de la serie, que diría que sí.

**El emisor.** La boleta de muestra la emite «INVERSIONES EN TELECOMUNICACIONES
DIGITALES S.A.C.» con RUC 20603110456 y dos direcciones -Jauja y La Oroya-. La
fila sembrada decía «INVERSIONES E.I.R.L.» con un RUC de relleno, que es lo que
se puso mientras no había dato real. Ahora lo hay.

Las dos direcciones van en el mismo campo separadas por salto de línea: son dos
renglones de la cabecera del papel, no dos domicilios que el sistema tenga que
distinguir. CABLE LOS ANDES y SPEEDY QUANTICO siguen con datos de relleno hasta
que lleguen los suyos.
"""

from django.db import migrations


# Los talonarios que pasan al tique. Se nombran uno a uno en vez de filtrarse
# por `series__startswith="B0"`: la lista es corta, se lee entera, y un block
# nuevo entra a mano, que es cuando alguien decide en qué papel se imprime.
EN_TIQUE = [
    "B001", "B001-INV",
    "B002", "B002-CLA",
    "B003-CLA", "B003-INV",
    "B004-CLA",
    "B006-CLA", "B006-INV",
    "B007-INV",
]


INVERSIONES = {
    "business_name": "INVERSIONES EN TELECOMUNICACIONES DIGITALES S.A.C.",
    "ruc": "20603110456",
    "address": "Av. Huancayo Nº215 - Jauja\nAv. Miguel Grau 127 - La Oroya",
    "phone": "064 466080",
}

# Lo que había antes, para poder deshacer.
INVERSIONES_ANTERIOR = {
    "business_name": "INVERSIONES E.I.R.L.",
    "ruc": "20000000002",
    "address": "Av. Huancayo Nº215 - Jauja",
    "phone": "064 466080",
}


def aplicar(apps, schema_editor):
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")
    Issuer = apps.get_model("payments", "Issuer")

    ReceiptSequence.objects.filter(code__in=EN_TIQUE).update(
        print_format="TICKET"
    )

    Issuer.objects.filter(code="INV").update(**INVERSIONES)


def deshacer(apps, schema_editor):
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")
    Issuer = apps.get_model("payments", "Issuer")

    ReceiptSequence.objects.filter(code__in=EN_TIQUE).update(
        print_format="SHEET"
    )

    Issuer.objects.filter(code="INV").update(**INVERSIONES_ANTERIOR)


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0013_formato_impreso_del_talonario"),
    ]

    operations = [
        migrations.RunPython(aplicar, deshacer),
    ]
