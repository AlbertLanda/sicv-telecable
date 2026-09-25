# Generated for transfer technical cost reconciliation.

import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("work_orders", "0028_transfer_operational_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="transferdetail",
            name="actual_extra_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                verbose_name="Adicional técnico real",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="reconciliation_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pendiente de costo real"),
                    ("MATCHED", "Sin diferencia"),
                    ("REQUIRES_DECISION", "Requiere regularización"),
                    ("RESOLVED", "Regularización resuelta"),
                ],
                default="PENDING",
                max_length=30,
                verbose_name="Estado de conciliación",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="reconciliation_action",
            field=models.CharField(
                blank=True,
                choices=[
                    ("CHARGE_DIFFERENCE", "Cobrar diferencia"),
                    ("NEXT_INVOICE", "Cargar diferencia a próxima mensualidad"),
                    ("KEEP_AGREED", "Mantener monto acordado"),
                    ("ABSORB", "Absorber diferencia / cortesía"),
                ],
                max_length=30,
                verbose_name="Decisión de regularización",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="reconciliation_note",
            field=models.TextField(
                blank=True,
                verbose_name="Sustento de regularización",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="reconciled_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Regularización resuelta el",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="reconciled_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reconciled_transfers",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Regularización resuelta por",
            ),
        ),
        migrations.AddField(
            model_name="workorderliquidationitem",
            name="is_billable",
            field=models.BooleanField(
                default=False,
                verbose_name="Facturable al abonado",
            ),
        ),
        migrations.AddField(
            model_name="workorderliquidationitem",
            name="unit_price",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                verbose_name="Precio unitario facturable",
            ),
        ),
        migrations.AlterModelOptions(
            name="transferdetail",
            options={
                "permissions": [
                    (
                        "resolve_transfer_reconciliation",
                        "Puede resolver regularizaciones económicas de traslados",
                    ),
                ],
                "verbose_name": "Detalle de traslado",
                "verbose_name_plural": "Detalles de traslado",
            },
        ),
    ]
