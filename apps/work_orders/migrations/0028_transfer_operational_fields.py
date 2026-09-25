# Generated for operational transfer workflow.

import django.db.models.deletion
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("work_orders", "0027_outside_plant_and_participation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="transferdetail",
            name="base_fee_snapshot",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=10,
                verbose_name="Tarifa base del traslado",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="estimated_extra_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=10,
                verbose_name="Adicional estimado",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="customer_agreed_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                verbose_name="Monto informado/aceptado por el abonado",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="charge_mode",
            field=models.CharField(
                choices=[
                    ("UPFRONT_FULL", "Cobrar monto informado al solicitar"),
                    ("UPFRONT_BASE", "Cobrar solo tarifa base al solicitar"),
                    ("AFTER_TECHNICAL", "Definir cobro después de constatación técnica"),
                ],
                default="UPFRONT_BASE",
                max_length=30,
                verbose_name="Momento de definición del cobro",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="collection_mode",
            field=models.CharField(
                choices=[
                    ("IMMEDIATE", "Cobrar el mismo día"),
                    ("NEXT_INVOICE", "Cargar a la próxima mensualidad"),
                ],
                default="IMMEDIATE",
                max_length=20,
                verbose_name="Forma prevista de cobro",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="requested_address_text",
            field=models.CharField(
                blank=True,
                max_length=250,
                verbose_name="Destino solicitado",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="requested_reference",
            field=models.CharField(
                blank=True,
                max_length=250,
                verbose_name="Referencia del destino solicitado",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="requested_supply_code",
            field=models.CharField(
                blank=True,
                max_length=50,
                verbose_name="Suministro informado",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="requested_latitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=7,
                max_digits=10,
                null=True,
                verbose_name="Latitud solicitada",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="requested_longitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=7,
                max_digits=10,
                null=True,
                verbose_name="Longitud solicitada",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="confirmed_supply_code",
            field=models.CharField(
                blank=True,
                max_length=50,
                verbose_name="Suministro confirmado",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="confirmed_latitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=7,
                max_digits=10,
                null=True,
                verbose_name="Latitud confirmada",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="confirmed_longitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=7,
                max_digits=10,
                null=True,
                verbose_name="Longitud confirmada",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="confirmed_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Destino confirmado el",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="confirmed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="confirmed_transfer_destinations",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Destino confirmado por",
            ),
        ),
        migrations.AlterField(
            model_name="transferdetail",
            name="new_address",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="transfer_destinations",
                to="customers.customeraddress",
                verbose_name="Nueva dirección confirmada",
            ),
        ),
    ]
