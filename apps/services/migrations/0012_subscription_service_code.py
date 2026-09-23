"""Código estable por suscripción/domicilio."""

from django.db import migrations, models


def poblar_codigos(apps, schema_editor):
    Subscription = apps.get_model("services", "Subscription")

    queryset = Subscription.objects.select_related(
        "customer",
        "service_type",
    ).order_by("pk")

    for subscription in queryset.iterator():
        subscription.service_code = (
            f"{subscription.customer.code}-"
            f"{subscription.service_type.code}-"
            f"{subscription.service_number:02d}"
        )
        subscription.save(update_fields=["service_code"])


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0011_catalogo_contratos_de_servicio"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="service_code",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=80,
                null=True,
                unique=True,
                verbose_name="Código de servicio",
            ),
        ),
        migrations.RunPython(poblar_codigos, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="subscription",
            name="service_code",
            field=models.CharField(
                blank=True,
                editable=False,
                help_text=(
                    "Identifica de forma estable esta suscripción/domicilio. "
                    "Un mismo abonado puede tener varios códigos de servicio."
                ),
                max_length=80,
                unique=True,
                verbose_name="Código de servicio",
            ),
        ),
    ]
