from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("customers", "0002_customeraddress_electrical_supply_code"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="customer",
            options={
                "ordering": [
                    "paternal_surname",
                    "maternal_surname",
                    "first_name",
                ],
                "permissions": [
                    (
                        "discard_incomplete_registration",
                        "Puede descartar altas comerciales incompletas",
                    ),
                ],
                "verbose_name": "Cliente",
                "verbose_name_plural": "Clientes",
            },
        ),
        migrations.CreateModel(
            name="IncompleteRegistrationDiscard",
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
                    "released_customer_code",
                    models.CharField(
                        db_index=True,
                        max_length=30,
                        verbose_name="Código de abonado liberado",
                    ),
                ),
                (
                    "branch_code",
                    models.CharField(
                        blank=True,
                        max_length=40,
                        verbose_name="Sede",
                    ),
                ),
                (
                    "stage",
                    models.CharField(
                        max_length=40,
                        verbose_name="Etapa descartada",
                    ),
                ),
                (
                    "reason",
                    models.TextField(verbose_name="Motivo"),
                ),
                (
                    "discarded_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Fecha de descarte",
                    ),
                ),
                (
                    "discarded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="incomplete_registration_discards",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Descartado por",
                    ),
                ),
            ],
            options={
                "verbose_name": "Descarte de alta incompleta",
                "verbose_name_plural": "Descartes de altas incompletas",
                "ordering": ["-discarded_at", "-pk"],
            },
        ),
    ]
