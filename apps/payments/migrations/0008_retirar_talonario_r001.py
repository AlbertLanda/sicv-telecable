from django.db import migrations, models


def retirar_r001(apps, schema_editor):
    """R001 deja de ofrecerse en la ventanilla.

    Era el talonario propio del sistema, el que se usó mientras no existía
    el padrón real. No se borra: tiene comprobantes ya entregados colgando,
    y un recibo sin el block del que salió no puede explicarse.
    """
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")

    ReceiptSequence.objects.filter(code="R001").update(is_active=False)


def devolver_r001(apps, schema_editor):
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")

    ReceiptSequence.objects.filter(code="R001").update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0007_talonarios_y_lugar_de_cobro"),
    ]

    operations = [
        migrations.AddField(
            model_name="receiptsequence",
            name="is_active",
            field=models.BooleanField(
                default=True,
                verbose_name="Se ofrece al cobrar",
            ),
        ),
        migrations.RunPython(retirar_r001, devolver_r001),
    ]
