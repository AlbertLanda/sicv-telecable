"""El contrato pasa a declarar el servicio que se firma.

Servicio, plan, modalidad, cuotas y los datos de cuenta PlayHub eran, hasta
ahora, algo que el contrato no decia: se leian de la suscripcion o no se
registraban en ninguna parte.

Servicio y plan entran nulos, se copian de la suscripcion de cada contrato y
solo entonces se cierran a obligatorios. Anadirlos obligatorios de una vez
habria exigido inventar un plan por defecto para los contratos que ya
existen, y el plan por defecto de un contrato firmado no existe: es el que
tiene su suscripcion.

`modality` queda vacia en los contratos anteriores. Es lo unico honesto: la
modalidad del equipo no se registraba, asi que no hay de donde deducirla. El
formulario la exige de ahora en adelante.
"""

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


def copiar_servicio_y_plan_de_la_suscripcion(apps, schema_editor):
    Contract = apps.get_model("contracts", "Contract")

    for contract in Contract.objects.select_related("subscription").iterator():
        contract.service_type_id = contract.subscription.service_type_id
        contract.plan_id = contract.subscription.plan_id
        contract.save(update_fields=["service_type", "plan"])


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0011_catalogo_contratos_de_servicio"),
        ("contracts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="modality",
            field=models.CharField(
                choices=[
                    ("SALE", "Venta"),
                    ("RENTAL", "Alquiler"),
                    ("OWNED", "Propio"),
                    ("LOAN", "Préstamo"),
                ],
                help_text="Cómo recibe el abonado el equipo del servicio contratado.",
                max_length=20,
                verbose_name="Modalidad",
            ),
        ),
        migrations.AddField(
            model_name="contract",
            name="installments",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text="Cuotas pactadas en el contrato. Sin financiamiento es 1.",
                validators=[django.core.validators.MinValueValidator(1)],
                verbose_name="Cuotas",
            ),
        ),
        migrations.AddField(
            model_name="contract",
            name="playhub_email",
            field=models.EmailField(
                blank=True,
                max_length=254,
                verbose_name="Correo PlayHub",
            ),
        ),
        migrations.AddField(
            model_name="contract",
            name="playhub_phone",
            field=models.CharField(
                blank=True,
                max_length=20,
                verbose_name="Celular PlayHub",
            ),
        ),
        migrations.AddField(
            model_name="contract",
            name="last_activation_date",
            field=models.DateField(
                blank=True,
                help_text=(
                    "La estampa el sistema cuando el servicio queda activo. "
                    "No se digita al registrar el contrato."
                ),
                null=True,
                verbose_name="Última activación",
            ),
        ),
        migrations.AddField(
            model_name="contract",
            name="service_type",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contracts",
                to="services.servicetype",
                verbose_name="Servicio",
            ),
        ),
        migrations.AddField(
            model_name="contract",
            name="plan",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contracts",
                to="services.plan",
                verbose_name="Plan",
            ),
        ),
        migrations.RunPython(
            copiar_servicio_y_plan_de_la_suscripcion,
            # Desandar no borra el dato copiado: los dos campos se eliminan
            # enteros en el paso anterior de la reversion.
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="contract",
            name="service_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contracts",
                to="services.servicetype",
                verbose_name="Servicio",
            ),
        ),
        migrations.AlterField(
            model_name="contract",
            name="plan",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contracts",
                to="services.plan",
                verbose_name="Plan",
            ),
        ),
    ]
