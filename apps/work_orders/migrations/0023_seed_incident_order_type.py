from django.db import migrations


def create_incident_order_type(apps, schema_editor):
    OrderType = apps.get_model("work_orders", "OrderType")

    OrderType.objects.update_or_create(
        code="INCIDENT",
        defaults={
            "name": "Incidencia",
            "description": "Atención lógica/remota gestionada por NOC",
            "is_active": True,
        },
    )


def remove_incident_order_type(apps, schema_editor):
    OrderType = apps.get_model("work_orders", "OrderType")

    OrderType.objects.filter(
        code="INCIDENT"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("work_orders", "0022_workorder_reason_text"),
    ]

    operations = [
        migrations.RunPython(
            create_incident_order_type,
            remove_incident_order_type,
        ),
    ]