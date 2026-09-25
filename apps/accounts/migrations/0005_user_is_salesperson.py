from django.db import migrations, models


def mark_existing_sales_role(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="SALES").update(is_salesperson=True)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_user_allowed_offices"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_salesperson",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Permite atribuirle ventas sin cambiar su rol operativo. "
                    "Un administrador o ATC puede vender y seguir conservando su rol."
                ),
                verbose_name="Participa como vendedor",
            ),
        ),
        migrations.RunPython(
            mark_existing_sales_role,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
