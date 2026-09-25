from django.db import migrations, models


def backfill_transfer_service_codes(apps, schema_editor):
    TransferDetail = apps.get_model("work_orders", "TransferDetail")

    for transfer in (
        TransferDetail.objects
        .select_related("work_order__subscription")
        .all()
    ):
        subscription = transfer.work_order.subscription
        if subscription is None:
            continue

        current_code = subscription.service_code or ""
        updates = []

        if not transfer.previous_service_code:
            transfer.previous_service_code = current_code
            updates.append("previous_service_code")

        if not transfer.resulting_service_code:
            transfer.resulting_service_code = current_code
            updates.append("resulting_service_code")

        if updates:
            transfer.save(update_fields=updates)


class Migration(migrations.Migration):

    dependencies = [
        ("work_orders", "0030_seed_transfer_catalog"),
    ]

    operations = [
        migrations.AddField(
            model_name="transferdetail",
            name="previous_service_code",
            field=models.CharField(
                blank=True,
                max_length=80,
                verbose_name="Código de servicio anterior",
            ),
        ),
        migrations.AddField(
            model_name="transferdetail",
            name="resulting_service_code",
            field=models.CharField(
                blank=True,
                max_length=80,
                verbose_name="Código de servicio resultante",
            ),
        ),
        migrations.RunPython(
            backfill_transfer_service_codes,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
