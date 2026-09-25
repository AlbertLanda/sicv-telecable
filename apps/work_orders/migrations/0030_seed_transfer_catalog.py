from django.db import migrations


TRANSFER_SERVICE_CODES = ("INTERNET", "CABLE", "DUO")


def seed_transfer_catalog(apps, schema_editor):
    OrderType = apps.get_model("work_orders", "OrderType")
    OrderSubtype = apps.get_model("work_orders", "OrderSubtype")
    OrderReason = apps.get_model("work_orders", "OrderReason")
    OrderResult = apps.get_model("work_orders", "OrderResult")
    ServiceType = apps.get_model("services", "ServiceType")

    transfer, _ = OrderType.objects.update_or_create(
        code="TRANSFER",
        defaults={
            "name": "TRASLADO",
            "description": (
                "Cambio de ubicación del servicio solicitado por el abonado."
            ),
            "is_active": True,
        },
    )

    service_types = list(
        ServiceType.objects.filter(code__in=TRANSFER_SERVICE_CODES)
    )
    if service_types:
        transfer.service_types.set(service_types)

    for code, name in (
        ("INTERNAL", "TRASLADO INTERNO"),
        ("EXTERNAL", "TRASLADO EXTERNO"),
    ):
        OrderSubtype.objects.update_or_create(
            order_type=transfer,
            code=code,
            defaults={
                "name": name,
                "is_active": True,
            },
        )

    for code, name, is_success in (
        ("SUCCESSFUL", "TRASLADO EJECUTADO", True),
        ("NOT_COMPLETED", "TRASLADO NO EJECUTADO", False),
    ):
        OrderResult.objects.update_or_create(
            order_type=transfer,
            code=code,
            defaults={
                "name": name,
                "is_success": is_success,
                "is_active": True,
            },
        )

    # Conserva el histórico de órdenes antiguas, pero deja de ofrecer
    # REQUERIMIENTO > TRASLADO para nuevas altas.
    OrderReason.objects.filter(
        order_type__code="REQUIREMENT",
        code="TRANSFER",
        is_active=True,
    ).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("work_orders", "0029_transfer_reconciliation"),
    ]

    operations = [
        migrations.RunPython(
            seed_transfer_catalog,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
