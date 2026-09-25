from django.db import migrations


def backfill_subscription_seller_from_installations(apps, schema_editor):
    Subscription = apps.get_model("services", "Subscription")
    WorkOrder = apps.get_model("work_orders", "WorkOrder")

    pending_ids = (
        Subscription.objects
        .filter(seller__isnull=True)
        .values_list("pk", flat=True)
    )

    for subscription_id in pending_ids.iterator():
        seller_ids = list(
            WorkOrder.objects
            .filter(
                subscription_id=subscription_id,
                order_type__code="INSTALLATION",
                seller__isnull=False,
            )
            .values_list("seller_id", flat=True)
            .distinct()[:2]
        )

        # Solo se recupera automáticamente cuando la evidencia histórica es
        # inequívoca. Si dos OTs atribuyeron vendedores distintos, se deja
        # pendiente para revisión humana.
        if len(seller_ids) == 1:
            Subscription.objects.filter(
                pk=subscription_id,
                seller__isnull=True,
            ).update(seller_id=seller_ids[0])


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0015_included_app_components"),
        ("work_orders", "0032_installation_withdrawal"),
    ]

    operations = [
        migrations.RunPython(
            backfill_subscription_seller_from_installations,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
