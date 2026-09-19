"""
La ventana de pronto pago de la linea 2026 es de 2 dias, no de 3.

El dato se levanto con 3 dias y negocio confirmo 2. Se corrige aqui y no en
el comando del catalogo porque el comando no crea politicas: las busca por
codigo, asi que la fila ya existe en toda instalacion y hay que actualizarla.
"""

from django.db import migrations


POLICY_CODE = "ANNIVERSARY_PP10"
CONFIRMED_DAYS = 2
PREVIOUS_DAYS = 3


def set_two_days(apps, schema_editor):
    BillingPolicy = apps.get_model("services", "BillingPolicy")

    BillingPolicy.objects.filter(code=POLICY_CODE).update(
        discount_days_before_due=CONFIRMED_DAYS,
    )


def restore_three_days(apps, schema_editor):
    BillingPolicy = apps.get_model("services", "BillingPolicy")

    BillingPolicy.objects.filter(code=POLICY_CODE).update(
        discount_days_before_due=PREVIOUS_DAYS,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0008_commercial_tiers"),
    ]

    operations = [
        migrations.RunPython(set_two_days, restore_three_days),
    ]
