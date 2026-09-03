from django.db import migrations


def seed_tv_annex_catalog(apps, schema_editor):
    OrderType = apps.get_model("work_orders", "OrderType")
    OrderSubtype = apps.get_model("work_orders", "OrderSubtype")
    OrderResult = apps.get_model("work_orders", "OrderResult")

    order_type, _ = OrderType.objects.get_or_create(
        code="TV_ANNEX",
        defaults={
            "name": "Anexos de TV",
            "description": (
                "Aumento o retiro de anexos de televisión sobre una "
                "suscripción CABLE/DUO existente."
            ),
            "is_active": True,
        },
    )

    OrderSubtype.objects.get_or_create(
        order_type=order_type,
        code="ADD",
        defaults={
            "name": "Aumento de anexos",
            "description": "Instalación de uno o más anexos adicionales.",
            "is_active": True,
        },
    )

    OrderSubtype.objects.get_or_create(
        order_type=order_type,
        code="REMOVE",
        defaults={
            "name": "Retiro de anexos",
            "description": "Retiro de uno o más anexos existentes.",
            "is_active": True,
        },
    )

    OrderResult.objects.get_or_create(
        order_type=order_type,
        code="COMPLETED",
        defaults={
            "name": "Ajuste de anexos ejecutado",
            "description": "El técnico completó el aumento o retiro solicitado.",
            "is_success": True,
            "is_active": True,
        },
    )

    OrderResult.objects.get_or_create(
        order_type=order_type,
        code="NOT_COMPLETED",
        defaults={
            "name": "Ajuste de anexos no ejecutado",
            "description": "La modificación solicitada no pudo ejecutarse.",
            "is_success": False,
            "is_active": True,
        },
    )


def unseed_tv_annex_catalog(apps, schema_editor):
    OrderType = apps.get_model("work_orders", "OrderType")
    OrderType.objects.filter(code="TV_ANNEX").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("work_orders", "0013_workorder_seller"),
    ]

    operations = [
        migrations.RunPython(
            seed_tv_annex_catalog,
            reverse_code=unseed_tv_annex_catalog,
        ),
    ]
