# Generated for historical SICAV contracts and work orders.

import decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("legacy", "0001_initial"),
        ("organization", "0004_office_is_deposit"),
        ("work_orders", "0035_seed_equipment_installation_reasons"),
    ]

    operations = [
        migrations.CreateModel(
            name="LegacyContractSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_contract_number", models.CharField(blank=True, max_length=60, verbose_name="Número de contrato SICAV")),
                ("service_name_snapshot", models.CharField(blank=True, max_length=160, verbose_name="Servicio histórico")),
                ("plan_name_snapshot", models.CharField(blank=True, max_length=180, verbose_name="Plan histórico")),
                ("equipment_snapshot", models.CharField(blank=True, max_length=180, verbose_name="Equipo histórico")),
                ("status", models.CharField(choices=[("DRAFT", "Borrador"), ("ACTIVE", "Activo"), ("SUSPENDED", "Suspendido"), ("CANCELLED", "Cancelado"), ("FINISHED", "Finalizado"), ("UNKNOWN", "Sin clasificar")], default="UNKNOWN", max_length=20, verbose_name="Estado histórico normalizado")),
                ("legacy_status", models.CharField(blank=True, max_length=80, verbose_name="Estado original")),
                ("modality", models.CharField(choices=[("SALE", "Venta"), ("RENTAL", "Alquiler"), ("OWNED", "Propio"), ("LOAN", "Préstamo"), ("UNKNOWN", "Sin clasificar")], default="UNKNOWN", max_length=20, verbose_name="Modalidad normalizada")),
                ("installments", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Cuotas")),
                ("start_date", models.DateField(verbose_name="Inicio")),
                ("end_date", models.DateField(blank=True, null=True, verbose_name="Fin")),
                ("last_activation_date", models.DateField(blank=True, null=True, verbose_name="Última activación")),
                ("last_cut_date", models.DateField(blank=True, null=True, verbose_name="Último corte")),
                ("notes", models.TextField(blank=True, verbose_name="Observaciones")),
                ("is_validated", models.BooleanField(default=False, verbose_name="Validado")),
                ("validation_notes", models.TextField(blank=True, verbose_name="Notas de validación")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="legacy_contracts", to="customers.customer", verbose_name="Abonado")),
                ("plan", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_contracts", to="services.plan", verbose_name="Plan normalizado")),
                ("service_type", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_contracts", to="services.servicetype", verbose_name="Servicio normalizado")),
                ("subscription", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="legacy_contracts", to="services.subscription", verbose_name="Suscripción")),
            ],
            options={
                "verbose_name": "Contrato histórico SICAV",
                "verbose_name_plural": "Contratos históricos SICAV",
                "ordering": ["subscription", "start_date", "pk"],
            },
        ),
        migrations.CreateModel(
            name="LegacyWorkOrderSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_order_number", models.CharField(blank=True, max_length=80, verbose_name="Número de orden SICAV")),
                ("order_type_name_snapshot", models.CharField(blank=True, max_length=160, verbose_name="Tipo histórico")),
                ("reason_name_snapshot", models.CharField(blank=True, max_length=180, verbose_name="Motivo histórico")),
                ("legacy_type_code", models.CharField(blank=True, max_length=30, verbose_name="Código de tipo original")),
                ("status", models.CharField(choices=[("PENDING", "Pendiente"), ("ASSIGNED", "Asignada"), ("DERIVED", "Derivada"), ("IN_PROGRESS", "En atención"), ("ATTENDED", "Atendida"), ("LIQUIDATED", "Liquidada"), ("REPROGRAMMED", "Reprogramada"), ("REJECTED", "Rechazada"), ("NOT_FEASIBLE", "No factible"), ("CANCELLED", "Anulada"), ("UNKNOWN", "Sin clasificar")], default="UNKNOWN", max_length=20, verbose_name="Estado normalizado")),
                ("legacy_status", models.CharField(blank=True, max_length=80, verbose_name="Estado original")),
                ("attention_type", models.CharField(choices=[("SYSTEM", "Sistema"), ("FIELD", "Física"), ("UNKNOWN", "Sin clasificar")], default="UNKNOWN", max_length=20, verbose_name="Tipo de atención")),
                ("responsibility", models.CharField(choices=[("CUSTOMER", "Cliente"), ("COMPANY", "Empresa"), ("OTHER", "Otros"), ("UNKNOWN", "Sin clasificar")], default="UNKNOWN", max_length=20, verbose_name="Responsabilidad")),
                ("detail", models.TextField(blank=True, verbose_name="Detalle de emisión")),
                ("attention_detail", models.TextField(blank=True, verbose_name="Detalle de atención / resultado")),
                ("technical_notes", models.TextField(blank=True, verbose_name="Observaciones técnicas")),
                ("issued_at", models.DateTimeField(blank=True, null=True, verbose_name="Emitida el")),
                ("attended_at", models.DateTimeField(blank=True, null=True, verbose_name="Atendida el")),
                ("nap", models.CharField(blank=True, max_length=100, verbose_name="NAP")),
                ("terminal", models.CharField(blank=True, max_length=40, verbose_name="Borne")),
                ("equipment_code", models.CharField(blank=True, max_length=160, verbose_name="MAC / equipo")),
                ("seal_number", models.CharField(blank=True, max_length=80, verbose_name="Precinto")),
                ("is_validated", models.BooleanField(default=False, verbose_name="Validado")),
                ("validation_notes", models.TextField(blank=True, verbose_name="Notas de validación")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="legacy_work_orders", to="organization.branch", verbose_name="Sede")),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="legacy_work_orders", to="customers.customer", verbose_name="Abonado")),
                ("derived_from", models.ForeignKey(blank=True, help_text="Solo se llena si el expediente confirma la relación. No se infiere únicamente por cercanía de fechas.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="derived_orders", to="legacy.legacyworkordersnapshot", verbose_name="Derivada de")),
                ("order_type", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_work_orders", to="work_orders.ordertype", verbose_name="Tipo normalizado")),
                ("reason", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_work_orders", to="work_orders.orderreason", verbose_name="Motivo normalizado")),
                ("subscription", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="legacy_work_orders", to="services.subscription", verbose_name="Suscripción")),
                ("zone", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_work_orders", to="organization.zone", verbose_name="Zona")),
            ],
            options={
                "verbose_name": "Orden histórica SICAV",
                "verbose_name_plural": "Órdenes históricas SICAV",
                "ordering": ["-issued_at", "-pk"],
            },
        ),
        migrations.CreateModel(
            name="LegacyWorkOrderEvidence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("original_name", models.CharField(blank=True, max_length=255, verbose_name="Nombre original")),
                ("legacy_reference", models.CharField(blank=True, help_text="Ruta/identificador histórico. No contiene cookies ni tokens.", max_length=500, verbose_name="Referencia SICAV")),
                ("file", models.FileField(blank=True, upload_to="legacy/work_orders/evidence/", verbose_name="Archivo migrado")),
                ("description", models.CharField(blank=True, max_length=240, verbose_name="Descripción")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evidences", to="legacy.legacyworkordersnapshot", verbose_name="Orden histórica")),
            ],
            options={
                "verbose_name": "Evidencia de OT histórica",
                "verbose_name_plural": "Evidencias de OT histórica",
                "ordering": ["work_order", "pk"],
            },
        ),
        migrations.CreateModel(
            name="LegacyWorkOrderMaterial",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_material_code", models.CharField(blank=True, max_length=80, verbose_name="Código SICAV")),
                ("name_snapshot", models.CharField(max_length=180, verbose_name="Material histórico")),
                ("quantity", models.DecimalField(decimal_places=5, max_digits=12, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.00001"))], verbose_name="Cantidad")),
                ("unit_snapshot", models.CharField(blank=True, max_length=40, verbose_name="Unidad")),
                ("movement_type", models.CharField(choices=[("INSTALLED", "Instalado"), ("REMOVED", "Retirado"), ("USED", "Utilizado")], default="USED", max_length=20, verbose_name="Movimiento")),
                ("notes", models.TextField(blank=True, verbose_name="Observación")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="materials", to="legacy.legacyworkordersnapshot", verbose_name="Orden histórica")),
            ],
            options={
                "verbose_name": "Material de OT histórica",
                "verbose_name_plural": "Materiales de OT histórica",
                "ordering": ["work_order", "pk"],
            },
        ),
        migrations.CreateModel(
            name="LegacyWorkOrderParticipant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_user_code", models.CharField(blank=True, max_length=80, verbose_name="Código de usuario SICAV")),
                ("name_snapshot", models.CharField(blank=True, max_length=180, verbose_name="Nombre histórico")),
                ("role_snapshot", models.CharField(blank=True, max_length=120, verbose_name="Rol / participación")),
                ("started_at", models.DateTimeField(blank=True, null=True, verbose_name="Inicio")),
                ("ended_at", models.DateTimeField(blank=True, null=True, verbose_name="Fin")),
                ("notes", models.TextField(blank=True, verbose_name="Observación")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participants", to="legacy.legacyworkordersnapshot", verbose_name="Orden histórica")),
            ],
            options={
                "verbose_name": "Participante de OT histórica",
                "verbose_name_plural": "Participantes de OT histórica",
                "ordering": ["work_order", "pk"],
            },
        ),
    ]
