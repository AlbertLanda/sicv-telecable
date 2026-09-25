# Generated for SICV transfer proposed charges.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0002_customeraddress_electrical_supply_code"),
        ("payments", "0017_codigo_sunat_del_talonario"),
        ("services", "0013_tv_cable_ftth_dos_puntos"),
        ("work_orders", "0027_outside_plant_and_participation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProposedCharge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("concept", models.CharField(choices=[("MONTHLY", "Mensualidad"), ("INSTALLATION", "Instalación"), ("ANNEX", "Anexo"), ("REACTIVATION", "Reconexión"), ("OTHER", "Otro concepto")], max_length=20, verbose_name="Concepto")),
                ("description", models.CharField(max_length=160, verbose_name="Detalle")),
                ("status", models.CharField(choices=[("PENDING", "Pendiente"), ("ACCEPTED", "Aceptada"), ("DISCARDED", "Descartada")], default="PENDING", max_length=20, verbose_name="Estado")),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="Observaciones")),
                ("resolved_at", models.DateTimeField(blank=True, null=True, verbose_name="Resuelta el")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("charge", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="proposal", to="payments.charge", verbose_name="Cargo emitido")),
                ("concept_item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="proposed_charges", to="payments.chargeconcept", verbose_name="Concepto del catálogo")),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="proposed_charges", to="customers.customer", verbose_name="Abonado")),
                ("resolved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="proposed_charges_resolved", to=settings.AUTH_USER_MODEL, verbose_name="Resuelta por")),
                ("subscription", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="proposed_charges", to="services.subscription", verbose_name="Suscripción")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="proposed_charges", to="work_orders.workorder", verbose_name="Orden que la origina")),
            ],
            options={
                "verbose_name": "Deuda propuesta",
                "verbose_name_plural": "Deudas propuestas",
                "ordering": ["-created_at", "-pk"],
                "permissions": [("resolve_proposedcharge", "Puede aceptar o descartar deudas propuestas")],
                "constraints": [models.UniqueConstraint(fields=("work_order", "concept_item"), name="payments_unique_proposal_per_order_concept")],
            },
        ),
    ]
