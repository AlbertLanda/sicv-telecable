from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0006_commercial_policies_tariffs_and_installation_rules"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="plan",
            options={
                "ordering": [
                    "-generation",
                    "commercial_category",
                    "service_type",
                    "speed_mbps",
                ],
                "verbose_name": "Plan",
                "verbose_name_plural": "Planes",
            },
        ),
    ]
