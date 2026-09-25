from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="workordermaterialmovement",
            name="is_billable",
            field=models.BooleanField(
                default=False,
                verbose_name="Facturable al abonado",
            ),
        ),
        migrations.AddField(
            model_name="workordermaterialmovement",
            name="unit_price",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.01"))
                ],
                verbose_name="Precio unitario facturable",
            ),
        ),
    ]
