from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models


PRODUCTS = (
    (
        "repetidor-4-antenas",
        "REPETIDOR 4 ANTENAS",
        "210.00",
        "venta-repetidor-4-antenas",
        "REPEATER",
    ),
    (
        "cubo-mesh",
        "CUBO MESH",
        "190.00",
        "venta-cubo-mesh",
        "MESH_INSTALL",
    ),
)


def seed_equipment_products(apps, schema_editor):
    ChargeConcept = apps.get_model("payments", "ChargeConcept")
    EquipmentProduct = apps.get_model("payments", "EquipmentProduct")

    for code, name, price, concept_code, reason_code in PRODUCTS:
        ChargeConcept.objects.update_or_create(
            code=concept_code,
            defaults={
                "name": f"VENTA {name}",
                "family": "OTHER",
                "is_active": True,
            },
        )

        EquipmentProduct.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "current_price": Decimal(price),
                "charge_concept_code": concept_code,
                "order_reason_code": reason_code,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0019_charge_component"),
        ("services", "0016_backfill_subscription_seller"),
        ("work_orders", "0035_seed_equipment_installation_reasons"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EquipmentProduct",
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
                    "code",
                    models.SlugField(
                        max_length=60,
                        unique=True,
                        verbose_name="Código",
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        max_length=120,
                        unique=True,
                        verbose_name="Equipo",
                    ),
                ),
                (
                    "current_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[MinValueValidator(Decimal("0.01"))],
                        verbose_name="Precio de venta",
                    ),
                ),
                (
                    "charge_concept_code",
                    models.SlugField(
                        max_length=80,
                        verbose_name="Concepto de cobranza",
                    ),
                ),
                (
                    "order_reason_code",
                    models.CharField(
                        max_length=30,
                        verbose_name="Motivo de instalación",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Activo"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Equipo vendible",
                "verbose_name_plural": "Equipos vendibles",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="EquipmentSale",
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
                    "price_snapshot",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[MinValueValidator(Decimal("0.01"))],
                        verbose_name="Precio vendido",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "charge",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment_sale",
                        to="payments.charge",
                        verbose_name="Deuda generada",
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment_sales",
                        to="customers.customer",
                        verbose_name="Abonado",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sales",
                        to="payments.equipmentproduct",
                        verbose_name="Equipo",
                    ),
                ),
                (
                    "registered_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment_sales_registered",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Registrado por",
                    ),
                ),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment_sales",
                        to="services.subscription",
                        verbose_name="Suscripción",
                    ),
                ),
                (
                    "work_order",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment_sale",
                        to="work_orders.workorder",
                        verbose_name="Orden de instalación",
                    ),
                ),
            ],
            options={
                "verbose_name": "Venta de equipo",
                "verbose_name_plural": "Ventas de equipos",
                "ordering": ["-created_at", "-pk"],
            },
        ),
        migrations.RunPython(
            seed_equipment_products,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
