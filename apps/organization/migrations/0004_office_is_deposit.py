from django.db import migrations, models


# Los depósitos que sembró 0003. Se marcan por código y no por nombre:
# «Deposito» es el nombre que hoy tienen las tres filas, pero el nombre
# se puede corregir desde el admin y el hecho de ser el depósito de la
# sede no debería depender de cómo alguien lo escriba.
DEPOSITOS = [
    "JAUJA-DEPOSITO",
    "HUANCAYO-DEPOSITO",
    "OROYA-DEPOSITO",
]


def marcar_depositos(apps, schema_editor):
    Office = apps.get_model("organization", "Office")

    Office.objects.filter(code__in=DEPOSITOS).update(is_deposit=True)


def desmarcar_depositos(apps, schema_editor):
    Office = apps.get_model("organization", "Office")

    Office.objects.filter(code__in=DEPOSITOS).update(is_deposit=False)


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0003_seed_oficinas_reales"),
    ]

    operations = [
        migrations.AddField(
            model_name="office",
            name="is_deposit",
            field=models.BooleanField(
                default=False,
                verbose_name="Es el deposito de la sede",
            ),
        ),
        migrations.AlterModelOptions(
            name="office",
            options={
                "ordering": ["branch", "is_deposit", "name"],
                "verbose_name": "Oficina",
                "verbose_name_plural": "Oficinas",
            },
        ),
        migrations.RunPython(marcar_depositos, desmarcar_depositos),
    ]
