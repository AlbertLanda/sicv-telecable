from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0003_subscription_unique_customer_service_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicetype",
            name="supports_tv_annexes",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Activar solo para servicios que incluyen señal de cable, "
                    "por ejemplo CABLE o DUO."
                ),
                verbose_name="Permite anexos de TV",
            ),
        ),
        migrations.AddField(
            model_name="servicetype",
            name="annex_installation_price",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("5.00"),
                help_text=(
                    "Cobro único por cada anexo nuevo. El retiro de anexos no "
                    "genera costo de instalación."
                ),
                max_digits=10,
                verbose_name="Costo de instalación por anexo",
            ),
        ),
        migrations.AddField(
            model_name="servicetype",
            name="annex_monthly_price",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("5.00"),
                max_digits=10,
                verbose_name="Cargo mensual por anexo",
            ),
        ),
        migrations.AddField(
            model_name="plan",
            name="included_tv_points",
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    "Cantidad de televisores incluidos sin costo de anexo. "
                    "Para planes CABLE/DUO actuales corresponde 2."
                ),
                verbose_name="TV incluidos",
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="annex_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    "Cantidad de anexos adicionales vigentes/solicitados. "
                    "Los TV incluidos por el plan no se cuentan como anexos."
                ),
                verbose_name="Anexos de TV",
            ),
        ),
    ]
