from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_user_is_salesperson"),
        ("services", "0013_tv_cable_ftth_dos_puntos"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="registered_by",
            field=models.ForeignKey(
                blank=True,
                help_text="Usuario que ingresó la contratación al SICV.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="registered_subscriptions",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Registrado por",
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="seller",
            field=models.ForeignKey(
                blank=True,
                help_text="Persona a quien se atribuye comercialmente esta venta.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sold_subscriptions",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Vendedor",
            ),
        ),
    ]
