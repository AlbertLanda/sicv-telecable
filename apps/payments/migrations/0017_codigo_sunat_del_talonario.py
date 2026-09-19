"""Cada talonario declara con qué código de SUNAT se identifica su documento.

El QR de un comprobante declarado no lleva el título del documento, lleva su
código del catálogo 01. Se supo escaneando el QR de una boleta real aceptada
-B003-0034430 de INVERSIONES-, que devolvió `03` donde nosotros escribíamos
«BOLETA DE VENTA ELECTRÓNICA».

El código va por talonario, al lado del título y del formato impreso, porque
es la misma clase de dato: qué es este block. Deducirlo del título lo ataría a
un texto libre que alguien puede reescribir, y el QR empezaría a salir mal sin
que nada avisara.

Los 34 talonarios se reparten por el título que ya tienen. El código por
defecto es `03` -boleta-, así que un block nuevo que nadie clasifique al menos
declara la clase más común en vez de quedarse vacío; los tres títulos de hoy
se fijan aquí uno a uno.

El `14` de los recibos de servicio público está pendiente de comprobar contra
un QR suyo: el que se escaneó era una boleta. Es un cambio de un carácter en
esta tabla si resultara ser otro.
"""

from django.db import migrations, models


# Título del documento -> código del catálogo 01 de SUNAT.
CODIGOS = {
    "FACTURA ELECTRÓNICA": "01",
    "BOLETA DE VENTA ELECTRÓNICA": "03",
    "RECIBO DE SERVICIO PÚBLICO ELECTRÓNICO": "14",
}


def clasificar(apps, schema_editor):
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")

    for titulo, codigo in CODIGOS.items():
        ReceiptSequence.objects.filter(document_title=titulo).update(
            sunat_code=codigo
        )


def deshacer(apps, schema_editor):
    """El campo se va entero con el AddField; no hay nada que devolver."""


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0016_rucs_reales_y_emisora_por_talonario'),
    ]

    operations = [
        migrations.AddField(
            model_name='receiptsequence',
            name='sunat_code',
            field=models.CharField(choices=[('01', 'Factura'), ('03', 'Boleta de venta'), ('14', 'Recibo por servicios públicos')], default='03', max_length=2, verbose_name='Código SUNAT del documento'),
        ),
        migrations.RunPython(clasificar, deshacer),
    ]
