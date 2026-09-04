from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


INITIAL_MATERIALS = [
    {"code": "CABLE_RG6", "name": "CABLE RG-6", "unit": "METER"},
    {"code": "CONECTOR_F56", "name": "CONECTOR F-56", "unit": "UNIT"},
    {"code": "SPLITTER_2", "name": "SPLITTER 2 SALIDAS", "unit": "UNIT"},
    {"code": "SPLITTER_3", "name": "SPLITTER 3 SALIDAS", "unit": "UNIT"},
    {"code": "SPLITTER_4", "name": "SPLITTER 4 SALIDAS", "unit": "UNIT"},
    {"code": "AISLADOR", "name": "AISLADOR", "unit": "UNIT"},
    {"code": "CABLE_UTP", "name": "CABLE UTP", "unit": "METER"},
    {"code": "FIBRA_DROP", "name": "FIBRA ÓPTICA DROP", "unit": "METER"},
]


def seed_materials(apps, schema_editor):
    Material = apps.get_model("inventory", "Material")
    for row in INITIAL_MATERIALS:
        Material.objects.update_or_create(
            code=row["code"],
            defaults={
                "name": row["name"],
                "unit_of_measure": row["unit"],
                "is_active": True,
            },
        )


def unseed_materials(apps, schema_editor):
    Material = apps.get_model("inventory", "Material")
    Material.objects.filter(code__in=[row["code"] for row in INITIAL_MATERIALS]).delete()


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("work_orders", "0014_seed_tv_annex_catalog"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Material",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=40, unique=True, verbose_name="Código")),
                ("name", models.CharField(max_length=150, verbose_name="Material")),
                ("unit_of_measure", models.CharField(choices=[("UNIT", "Unidad"), ("METER", "Metro"), ("ROLL", "Rollo"), ("SET", "Juego")], default="UNIT", max_length=20, verbose_name="Unidad de medida")),
                ("is_active", models.BooleanField(default=True, verbose_name="Activo")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Material",
                "verbose_name_plural": "Materiales",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="WorkOrderMaterialMovement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("movement_type", models.CharField(choices=[("INSTALLED", "Instalado en domicilio"), ("REMOVED", "Retirado de domicilio")], max_length=20, verbose_name="Tipo de movimiento")),
                ("quantity", models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))], verbose_name="Cantidad")),
                ("remarks", models.CharField(blank=True, max_length=250, verbose_name="Observación")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("material", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="work_order_movements", to="inventory.material", verbose_name="Material")),
                ("recorded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="recorded_work_order_materials", to=settings.AUTH_USER_MODEL, verbose_name="Registrado por")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="field_material_movements", to="work_orders.workorder", verbose_name="Orden de trabajo")),
            ],
            options={
                "verbose_name": "Movimiento de material en OT",
                "verbose_name_plural": "Movimientos de materiales en OT",
                "ordering": ["movement_type", "material__name"],
            },
        ),
        migrations.AddConstraint(
            model_name="workordermaterialmovement",
            constraint=models.UniqueConstraint(fields=("work_order", "material", "movement_type"), name="unique_material_movement_per_work_order"),
        ),
        migrations.AddIndex(
            model_name="workordermaterialmovement",
            index=models.Index(fields=["work_order", "movement_type"], name="inv_wo_material_move_idx"),
        ),
        migrations.RunPython(seed_materials, reverse_code=unseed_materials),
    ]
