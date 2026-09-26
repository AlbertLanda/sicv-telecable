from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0014_subscription_sales_attribution"),
    ]

    operations = [
        migrations.AddField(
            model_name="plan",
            name="included_app_component_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text=(
                    "Parte interna de la mensualidad total que corresponde a "
                    "la APP. No se suma al precio del paquete."
                ),
                max_digits=10,
                verbose_name="Componente mensual APP (S/)",
            ),
        ),
        migrations.AddField(
            model_name="plan",
            name="included_app_plan",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Derecho APP incluido dentro del precio del paquete. "
                    "Debe apuntar a un plan del servicio APPS."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="included_in_packages",
                to="services.plan",
                verbose_name="APP incluida",
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="included_app_component_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text=(
                    "Snapshot económico de la parte de la mensualidad incluida "
                    "que corresponde a la APP. No incrementa el total."
                ),
                max_digits=10,
                verbose_name="Componente mensual APP contratado",
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="included_app_plan",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="package_subscriptions",
                to="services.plan",
                verbose_name="APP incluida contratada",
            ),
        ),
    ]
