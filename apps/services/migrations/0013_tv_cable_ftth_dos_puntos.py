"""Confirma dos puntos de TV incluidos en los planes Cable FTTH."""

from django.db import migrations


PLAN_CODES = ("TVC-FTTH-40", "TVC-FTTH-50")


def aplicar_dos_puntos(apps, schema_editor):
    Plan = apps.get_model("services", "Plan")
    Plan.objects.filter(code__in=PLAN_CODES).update(included_tv_points=2)


def volver_a_cero(apps, schema_editor):
    Plan = apps.get_model("services", "Plan")
    Plan.objects.filter(code__in=PLAN_CODES).update(included_tv_points=0)


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0012_subscription_service_code"),
    ]

    operations = [
        migrations.RunPython(aplicar_dos_puntos, volver_a_cero),
    ]
}
