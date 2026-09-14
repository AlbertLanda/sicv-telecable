import django.db.models.deletion
from django.db import migrations, models


# Los talonarios del sistema que se reemplaza, en su orden y con el
# correlativo que les toca ahora.
#
# El número que se anotó es el PRÓXIMO a imprimir, no el último
# entregado, así que `last_number` se guarda uno por debajo: el primer
# cobro que salga de B001 llevará el 0041314 que el operador espera.
#
# Los blocks de un cobrador (JU*, MR*, ST*) no numeran solos: son papel
# que él ya trae numerado, y el operador escribe el número que toca.
TALONARIOS = [
    # code, serie impresa, etiqueta, próximo número (None = a mano)
    ("JU1", "JU1", "B: JU1 - JUAN URBAJO", None),
    ("JU2", "JU2", "B: JU2 - JUAN URBAJO", None),
    ("JU3", "JU3", "B: JU3 - JUAN URBAJO", None),
    ("MR3", "MR3", "B: MR3 - MARY ROJAS", None),
    ("MR4", "MR4", "B: MR4 - MARY ROJAS", None),
    ("ST1", "ST1", "B: ST1 - STEFAN", None),
    ("ST2", "ST2", "B: ST2 - STEFAN", None),
    ("ST3", "ST3", "B: ST3 - STEFAN", None),
    ("ST4", "ST4", "B: ST4 - STEFAN", None),
    ("ST5", "ST5", "B: ST5 - STEFAN", None),
    ("B001", "B001", "B:B001 - CABLE LOS ANDES", 41314),
    ("B002", "B002", "B:B002 - INVERSIONES", 31981),
    ("F001", "F001", "F:F001 - CABLE LOS ANDES", 8323),
    ("F002", "F002", "F:F002 - INVERSIONES", 5597),
    # «S010» nombra tres blocks distintos, cada uno por su cuenta. Por eso
    # el código los separa y la serie impresa se repite.
    ("S010-VELOCIDAD", "S010", "S:S010 - VELOCIDAD", 3031),
    ("S010-RED-OPTICA", "S010", "S:S010 - RED OPTICA", 267),
    ("S010-SPEEDY", "S010", "S:S010 - SPEEDY", 569),
    ("VCOND", "V.COND", "V.COND - CABLE LOS ANDES", 30821),
]


def rellenar_talonarios_existentes(apps, schema_editor):
    """Las filas que ya existían se describen a sí mismas.

    Antes de esto una fila era solo «serie + último número», así que su
    código y su etiqueta son su propia serie: R001 se sigue llamando R001.
    """
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")

    for sequence in ReceiptSequence.objects.all():
        ReceiptSequence.objects.filter(pk=sequence.pk).update(
            code=sequence.series,
            label=sequence.series,
        )


def seed_talonarios(apps, schema_editor):
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")

    # R001 es el talonario propio del sistema -el que ya tiene recibos
    # emitidos y el que se usa cuando no se elige ninguno-, así que
    # encabeza la lista y los del sistema anterior van detrás.
    ReceiptSequence.objects.filter(code="R001").update(position=0)

    for orden, (code, series, label, proximo) in enumerate(TALONARIOS, start=1):
        ReceiptSequence.objects.update_or_create(
            code=code,
            defaults={
                "series": series,
                "label": label,
                "position": orden,
                "autonumber": proximo is not None,
                "last_number": (proximo - 1) if proximo else 0,
            },
        )


def eliminar_talonarios(apps, schema_editor):
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")

    # Solo los que no llegaron a emitir nada: borrar uno con recibos
    # dejaría comprobantes entregados sin el block del que salieron.
    ReceiptSequence.objects.filter(
        code__in=[code for code, _, _, _ in TALONARIOS],
        receipts__isnull=True,
    ).delete()


def amarrar_recibos_a_su_talonario(apps, schema_editor):
    """Cada recibo ya emitido queda colgado del block de su serie."""
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")
    Receipt = apps.get_model("payments", "Receipt")

    for receipt in Receipt.objects.filter(sequence__isnull=True):
        sequence, _ = ReceiptSequence.objects.get_or_create(
            code=receipt.series,
            defaults={
                "series": receipt.series,
                "label": receipt.series,
            },
        )

        Receipt.objects.filter(pk=receipt.pk).update(sequence=sequence)


def sin_vuelta(apps, schema_editor):
    """Deshacer no necesita tocar datos: la columna se va entera."""


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0003_seed_oficinas_reales"),
        ("payments", "0006_seed_charge_concepts"),
    ]

    operations = [
        # --- El talonario gana identidad propia -------------------------
        migrations.AddField(
            model_name="receiptsequence",
            name="code",
            field=models.CharField(
                default="",
                max_length=20,
                verbose_name="Código del talonario",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="receiptsequence",
            name="label",
            field=models.CharField(
                default="",
                help_text="Como se lee en el desplegable de cobro.",
                max_length=80,
                verbose_name="Etiqueta",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="receiptsequence",
            name="autonumber",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Si no numera sola, el operador escribe el número del "
                    "block."
                ),
                verbose_name="Numera sola",
            ),
        ),
        migrations.AddField(
            model_name="receiptsequence",
            name="position",
            field=models.PositiveSmallIntegerField(
                default=0,
                verbose_name="Orden en la lista",
            ),
        ),
        migrations.RunPython(rellenar_talonarios_existentes, sin_vuelta),
        migrations.AlterField(
            model_name="receiptsequence",
            name="code",
            field=models.CharField(
                max_length=20,
                unique=True,
                verbose_name="Código del talonario",
            ),
        ),
        # La serie impresa deja de ser única: los tres S010 la comparten.
        migrations.AlterField(
            model_name="receiptsequence",
            name="series",
            field=models.CharField(max_length=8, verbose_name="Serie impresa"),
        ),
        migrations.AlterModelOptions(
            name="receiptsequence",
            options={
                "ordering": ["position", "label"],
                "verbose_name": "Talonario de comprobantes",
                "verbose_name_plural": "Talonarios de comprobantes",
            },
        ),

        # --- El recibo dice de qué block salió --------------------------
        migrations.RemoveConstraint(
            model_name="receipt",
            name="payments_receipt_unique_series_number",
        ),
        migrations.AddField(
            model_name="receipt",
            name="sequence",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="receipts",
                to="payments.receiptsequence",
                verbose_name="Talonario",
            ),
        ),
        migrations.RunPython(amarrar_recibos_a_su_talonario, sin_vuelta),
        migrations.AlterField(
            model_name="receipt",
            name="sequence",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="receipts",
                to="payments.receiptsequence",
                verbose_name="Talonario",
            ),
        ),
        migrations.AddConstraint(
            model_name="receipt",
            constraint=models.UniqueConstraint(
                fields=("sequence", "number"),
                name="payments_receipt_unique_sequence_number",
            ),
        ),

        # --- Dónde entró el dinero --------------------------------------
        migrations.AddField(
            model_name="payment",
            name="office",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payments",
                to="organization.office",
                verbose_name="Lugar de cobro",
            ),
        ),

        # --- Los talonarios del sistema anterior ------------------------
        migrations.RunPython(seed_talonarios, eliminar_talonarios),
    ]
