from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("organization", "0004_office_is_deposit")]
    operations = [
        migrations.AlterModelOptions(
            name="branch",
            options={
                "ordering": ["name"],
                "verbose_name": "Sede",
                "verbose_name_plural": "Sedes",
                "permissions": [
                    (
                        "view_operational_dashboard",
                        "Puede consultar el panel administrativo y sus detalles",
                    ),
                    (
                        "view_consolidated_dashboard",
                        "Puede consolidar las sedes en el panel administrativo",
                    ),
                ],
            },
        ),
    ]
