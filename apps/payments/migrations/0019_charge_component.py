from django.db import migrations, models
import django.db.models.deletion
from django.core.validators import MinValueValidator
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0018_deuda_propuesta_por_traslado"),
        ("services", "0015_included_app_components"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChargeComponent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("MAIN", "Servicio principal"),
                            ("INCLUDED_APP", "APP incluida"),
                        ],
                        max_length=20,
                        verbose_name="Componente",
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        blank=True,
                        max_length=40,
                        verbose_name="Código",
                    ),
                ),
                (
                    "description",
                    models.CharField(
                        max_length=160,
                        verbose_name="Detalle",
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[MinValueValidator(Decimal("0.01"))],
                        verbose_name="Monto incluido",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "charge",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="components",
                        to="payments.charge",
                        verbose_name="Cargo",
                    ),
                ),
            ],
            options={
                "verbose_name": "Componente de cargo",
                "verbose_name_plural": "Componentes de cargos",
                "ordering": ["charge", "kind", "pk"],
            },
        ),
        migrations.AddConstraint(
            model_name="chargecomponent",
            constraint=models.UniqueConstraint(
                fields=("charge", "kind"),
                name="payments_unique_charge_component_kind",
            ),
        ),
    ]
