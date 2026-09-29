# Generated for SICAV legacy migration support.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("customers", "0003_incomplete_registration_discard"),
        ("services", "0018_subscription_plan_history"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LegacyRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(choices=[("SICAV", "SICAV")], default="SICAV", max_length=20, verbose_name="Origen")),
                ("entity_type", models.CharField(choices=[("CUSTOMER", "Abonado"), ("ADDRESS", "Dirección"), ("SUBSCRIPTION", "Suscripción"), ("CONTRACT", "Contrato"), ("PLAN_HISTORY", "Historial de plan"), ("WORK_ORDER", "Orden de trabajo"), ("CHARGE", "Cargo / deuda"), ("PAYMENT", "Pago"), ("RECEIPT", "Comprobante"), ("EVIDENCE", "Evidencia"), ("EQUIPMENT", "Equipo"), ("AUDIT_EVENT", "Auditoría")], max_length=30, verbose_name="Tipo de registro")),
                ("legacy_id", models.CharField(max_length=120, verbose_name="ID en sistema anterior")),
                ("target_object_id", models.PositiveBigIntegerField(blank=True, null=True, verbose_name="ID de objeto normalizado")),
                ("raw_payload", models.JSONField(default=dict, help_text="Copia inmutable del dato recuperado de SICAV.", verbose_name="Payload original")),
                ("normalized_payload", models.JSONField(blank=True, default=dict, help_text="Representación editable usada para revisar o corregir el mapeo sin modificar el dato original.", verbose_name="Interpretación normalizada")),
                ("review_status", models.CharField(choices=[("IMPORTED", "Importado"), ("REVIEW", "Por revisar"), ("VALIDATED", "Validado"), ("CORRECTED", "Corregido")], default="IMPORTED", max_length=20, verbose_name="Estado de revisión")),
                ("review_notes", models.TextField(blank=True, verbose_name="Notas de revisión")),
                ("validated_at", models.DateTimeField(blank=True, null=True, verbose_name="Validado el")),
                ("imported_at", models.DateTimeField(auto_now_add=True, verbose_name="Importado el")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Actualizado el")),
                ("customer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_records", to="customers.customer", verbose_name="Abonado SICV")),
                ("imported_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_records_imported", to=settings.AUTH_USER_MODEL, verbose_name="Importado por")),
                ("subscription", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_records", to="services.subscription", verbose_name="Suscripción SICV")),
                ("target_content_type", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_records", to="contenttypes.contenttype", verbose_name="Tipo de objeto normalizado")),
                ("validated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_records_validated", to=settings.AUTH_USER_MODEL, verbose_name="Validado por")),
            ],
            options={
                "verbose_name": "Registro legacy",
                "verbose_name_plural": "Registros legacy",
                "ordering": ["entity_type", "legacy_id"],
            },
        ),
        migrations.CreateModel(
            name="LegacyRecordCorrection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("previous_payload", models.JSONField(default=dict, verbose_name="Valor anterior")),
                ("new_payload", models.JSONField(default=dict, verbose_name="Valor nuevo")),
                ("reason", models.TextField(verbose_name="Motivo de la corrección")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de corrección")),
                ("corrected_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_record_corrections", to=settings.AUTH_USER_MODEL, verbose_name="Corregido por")),
                ("record", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="corrections", to="legacy.legacyrecord", verbose_name="Registro legacy")),
            ],
            options={
                "verbose_name": "Corrección legacy",
                "verbose_name_plural": "Correcciones legacy",
                "ordering": ["-created_at", "-pk"],
            },
        ),
        migrations.AddConstraint(
            model_name="legacyrecord",
            constraint=models.UniqueConstraint(fields=("source", "entity_type", "legacy_id"), name="legacy_unique_source_entity_id"),
        ),
        migrations.AddIndex(
            model_name="legacyrecord",
            index=models.Index(fields=["source", "entity_type", "legacy_id"], name="legacy_source_entity_idx"),
        ),
        migrations.AddIndex(
            model_name="legacyrecord",
            index=models.Index(fields=["review_status"], name="legacy_review_status_idx"),
        ),
    ]
