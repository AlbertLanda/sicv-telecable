import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0004_annexes_and_subscription_rules"),
        ("work_orders", "0014_seed_tv_annex_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionAnnexAdjustment",
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
                    "operation",
                    models.CharField(
                        choices=[
                            ("ADD", "Aumento de anexos"),
                            ("REMOVE", "Retiro de anexos"),
                        ],
                        max_length=10,
                        verbose_name="Operación",
                    ),
                ),
                (
                    "previous_annex_count",
                    models.PositiveIntegerField(verbose_name="Anexos antes"),
                ),
                (
                    "quantity",
                    models.PositiveIntegerField(verbose_name="Cantidad a modificar"),
                ),
                (
                    "target_annex_count",
                    models.PositiveIntegerField(verbose_name="Anexos resultantes"),
                ),
                (
                    "installation_charge",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        max_digits=10,
                        verbose_name="Cobro único de instalación",
                    ),
                ),
                (
                    "monthly_delta",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        max_digits=10,
                        verbose_name="Variación mensual",
                    ),
                ),
                (
                    "monthly_charge_after",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        max_digits=10,
                        verbose_name="Cargo mensual de anexos resultante",
                    ),
                ),
                (
                    "applied_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Aplicado en la suscripción",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="annex_adjustments",
                        to="services.subscription",
                        verbose_name="Suscripción",
                    ),
                ),
                (
                    "work_order",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="annex_adjustment",
                        to="work_orders.workorder",
                        verbose_name="Orden de trabajo",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ajuste de anexos",
                "verbose_name_plural": "Ajustes de anexos",
                "ordering": ["-created_at"],
            },
        ),
    ]
