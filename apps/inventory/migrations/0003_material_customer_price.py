"""Precio al abonado de los materiales cobrables en una avería.

Cuando una avería es responsabilidad del cliente, lo que el técnico deja
instalado se le cobra a estos precios, más la atención de la avería. Los
materiales que faltaban en el catálogo se crean aquí para que el técnico
pueda declararlos desde el portal.

Se siembra sin pisar lo que ya exista: si alguien corrigió un precio desde el
admin, volver a correr las migraciones no lo devuelve al de la tabla.
"""

from decimal import Decimal

import django.core.validators
from django.db import migrations, models


# (código, nombre, unidad, precio al abonado)
TARIFARIO_AVERIA = [
    ("CONECTOR_MECANICO", "CONECTOR MECÁNICO", "UNIT", "25.00"),
    ("ENFRENTADOR", "ENFRENTADOR", "UNIT", "10.00"),
    ("ONU", "ONU", "UNIT", "100.00"),
    ("CARGADOR", "CARGADOR", "UNIT", "10.00"),
    ("CABLE_RG6", "CABLE RG-6", "METER", "1.00"),
    ("CABLE_UTP", "CABLE UTP", "METER", "2.00"),
    ("RJ45", "CONECTOR RJ45", "UNIT", "1.00"),
]

MATERIALES_NUEVOS = {
    "CONECTOR_MECANICO",
    "ENFRENTADOR",
    "ONU",
    "CARGADOR",
    "RJ45",
}


def sembrar_tarifario(apps, schema_editor):
    Material = apps.get_model("inventory", "Material")

    for code, name, unit, price in TARIFARIO_AVERIA:
        material, _created = Material.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "unit_of_measure": unit,
                "is_active": True,
            },
        )

        if material.customer_price is None:
            material.customer_price = Decimal(price)
            material.save(update_fields=["customer_price"])


def retirar_tarifario(apps, schema_editor):
    Material = apps.get_model("inventory", "Material")

    # Solo se retiran los materiales que esta migración creó y que nadie
    # llegó a declarar en una orden: los usados quedan protegidos por la OT.
    Material.objects.filter(
        code__in=MATERIALES_NUEVOS,
        work_order_movements__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_work_order_material_billing"),
    ]

    operations = [
        migrations.AddField(
            model_name="material",
            name="customer_price",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text=(
                    "Se cobra por unidad de medida cuando la avería es "
                    "responsabilidad del cliente. Vacío: no se cobra."
                ),
                max_digits=10,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.01"))
                ],
                verbose_name="Precio al abonado",
            ),
        ),
        migrations.RunPython(sembrar_tarifario, reverse_code=retirar_tarifario),
    ]
