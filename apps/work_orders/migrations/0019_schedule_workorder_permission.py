from django.db import migrations


PERMISSION_CODENAME = "schedule_workorder"
PERMISSION_NAME = "Puede programar y reprogramar órdenes de trabajo"


def create_schedule_permission(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="work_orders",
        model="workorder",
    )
    Permission.objects.update_or_create(
        content_type=content_type,
        codename=PERMISSION_CODENAME,
        defaults={"name": PERMISSION_NAME},
    )


def remove_schedule_permission(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")

    content_type = ContentType.objects.filter(
        app_label="work_orders",
        model="workorder",
    ).first()
    if content_type is not None:
        Permission.objects.filter(
            content_type=content_type,
            codename=PERMISSION_CODENAME,
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("work_orders", "0018_reprogramming_dia_sin_hora"),
    ]

    operations = [
        migrations.RunPython(
            create_schedule_permission,
            remove_schedule_permission,
        ),
    ]
