from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_phone"),
        ("organization", "0004_office_is_deposit"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="allowed_offices",
            field=models.ManyToManyField(
                blank=True,
                related_name="authorized_users",
                to="organization.office",
                verbose_name="Oficinas habilitadas para cobro",
            ),
        ),
    ]
