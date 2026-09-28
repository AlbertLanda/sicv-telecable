from django.db import migrations


def seed_equipment_installation_reasons(apps, schema_editor):
    OrderType = apps.get_model("work_orders", "OrderType")
    OrderReason = apps.get_model("work_orders", "OrderReason")

    requirement, _ = OrderType.objects.update_or_create(
        code="REQUIREMENT",
        defaults={
            "name": "REQUERIMIENTO",
            "description": "Solicitud del abonado que no es avería ni alta ni baja.",
            "is_active": True,
        },
    )

    for code, name in (
        ("REPEATER", "INSTALACIÓN DE REPETIDOR"),
        ("MESH_INSTALL", "INSTALACIÓN DE CUBO MESH"),
    ):
        OrderReason.objects.update_or_create(
            order_type=requirement,
            code=code,
            defaults={
                "name": name,
                "classification": "TECHNICAL",
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("work_orders", "0034_merge_20260926_0830"),
    ]

    operations = [
        migrations.RunPython(
            seed_equipment_installation_reasons,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
