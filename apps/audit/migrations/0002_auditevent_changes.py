from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditevent",
            name="changes",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Valores anterior y nuevo de los campos modificados.",
                verbose_name="Cambios",
            ),
        ),
    ]
