"""Registrar la emisora identificada sin inventar series ni correlativos."""
from django.db import migrations


def seed_econet(apps, schema_editor):
    issuers = apps.get_model("payments", "Issuer").objects.using(schema_editor.connection.alias)
    if not issuers.filter(ruc="20615039757").exists():
        issuers.get_or_create(code="ECO", defaults={
            "business_name": "ECONET E.I.R.L.", "ruc": "20615039757",
        })


class Migration(migrations.Migration):
    dependencies = [("payments", "0023_charge_period_start_charge_source_cut_order")]
    operations = [migrations.RunPython(seed_econet, migrations.RunPython.noop)]
