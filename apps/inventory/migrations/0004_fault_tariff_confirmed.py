"""Ajusta el tarifario confirmado de materiales cobrables en averías.

Reglas operativas confirmadas:
- conector mecánico: S/ 25 por unidad
- fibra Drop: S/ 1 por metro
- enfrentador: S/ 10 por unidad
- ONU: S/ 100 por unidad
- router: S/ 100 por unidad
- cargador: S/ 10 por unidad
- UTP: S/ 2 por metro
- RJ45: S/ 1 por unidad
- RG6: S/ 1 por metro

ONU y router se mantienen como materiales distintos aunque operativamente
suelan llamarse de forma indistinta.
"""

from decimal import Decimal

from django.db import migrations


TARIFARIO = [
    ("CONECTOR_MECANICO", "CONECTOR MECÁNICO", "UNIT", "25.00"),
    ("FIBRA_DROP", "FIBRA ÓPTICA DROP", "METER", "1.00"),
    ("ENFRENTADOR", "ENFRENTADOR", "UNIT", "10.00"),
    ("ONU", "ONU", "UNIT", "100.00"),
    ("ROUTER", "ROUTER", "UNIT", "100.00"),
    ("CARGADOR", "CARGADOR", "UNIT", "10.00"),
    ("CABLE_UTP", "CABLE UTP", "METER", "2.00"),
    ("RJ45", "CONECTOR RJ45", "UNIT", "1.00"),
    ("CABLE_RG6", "CABLE RG-6", "METER", "1.00"),
]


def aplicar_tarifario(apps, schema_editor):
    Material = apps.get_model("inventory", "Material")

    for code, name, unit, price in TARIFARIO:
        material, _created = Material.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "unit_of_measure": unit,
                "is_active": True,
            },
        )
        material.name = name
        material.unit_of_measure = unit
        material.customer_price = Decimal(price)
        material.is_active = True
        material.save(
            update_fields=[
                "name",
                "unit_of_measure",
                "customer_price",
                "is_active",
                "updated_at",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0003_material_customer_price"),
    ]

    operations = [
        migrations.RunPython(
            aplicar_tarifario,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
