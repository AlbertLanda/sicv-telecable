# Generated for historical SICAV finance snapshots.

import decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("legacy", "0002_contracts_work_orders_history"),
    ]

    operations = [
        migrations.AlterField(
            model_name="legacyrecord",
            name="entity_type",
            field=models.CharField(
                choices=[
                    ("CUSTOMER", "Abonado"),
                    ("ADDRESS", "Dirección"),
                    ("SUBSCRIPTION", "Suscripción"),
                    ("CONTRACT", "Contrato"),
                    ("PLAN_HISTORY", "Historial de plan"),
                    ("WORK_ORDER", "Orden de trabajo"),
                    ("CHARGE", "Cargo / deuda"),
                    ("PAYMENT", "Pago"),
                    ("PAYMENT_ALLOCATION", "Aplicación de pago"),
                    ("RECEIPT", "Comprobante"),
                    ("EVIDENCE", "Evidencia"),
                    ("EQUIPMENT", "Equipo"),
                    ("AUDIT_EVENT", "Auditoría"),
                ],
                max_length=30,
                verbose_name="Tipo de registro",
            ),
        ),
        migrations.CreateModel(
            name="LegacyChargeSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("description", models.CharField(max_length=180, verbose_name="Concepto histórico")),
                ("quantity", models.DecimalField(decimal_places=5, default=decimal.Decimal("1.00000"), max_digits=12, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.00001"))], verbose_name="Cantidad")),
                ("currency", models.CharField(default="PEN", max_length=3, verbose_name="Moneda")),
                ("period_start", models.DateField(blank=True, null=True, verbose_name="Periodo desde")),
                ("period_end", models.DateField(blank=True, null=True, verbose_name="Periodo hasta")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.01"))], verbose_name="Monto histórico")),
                ("due_date", models.DateField(blank=True, null=True, verbose_name="Vencimiento")),
                ("legacy_date", models.DateField(blank=True, help_text="Fecha conservada desde SICAV cuya semántica exacta todavía puede estar pendiente de validación.", null=True, verbose_name="Fecha legacy")),
                ("document_snapshot", models.CharField(blank=True, max_length=120, verbose_name="Documento mostrado")),
                ("observation", models.TextField(blank=True, verbose_name="Observación")),
                ("status", models.CharField(choices=[("PAID", "Pagado"), ("PENDING", "Pendiente"), ("CANCELLED", "Anulado"), ("UNKNOWN", "Sin clasificar")], default="PAID", max_length=20, verbose_name="Estado histórico")),
                ("is_validated", models.BooleanField(default=False, verbose_name="Validado")),
                ("validation_notes", models.TextField(blank=True, verbose_name="Notas de validación")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="legacy_charge_snapshots", to="customers.customer", verbose_name="Abonado")),
                ("subscription", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_charge_snapshots", to="services.subscription", verbose_name="Suscripción")),
            ],
            options={
                "verbose_name": "Cargo histórico SICAV",
                "verbose_name_plural": "Cargos históricos SICAV",
                "ordering": ["period_start", "due_date", "pk"],
            },
        ),
        migrations.CreateModel(
            name="LegacyPaymentSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.01"))], verbose_name="Total histórico")),
                ("currency", models.CharField(default="PEN", max_length=3, verbose_name="Moneda")),
                ("method_code", models.CharField(blank=True, max_length=30, verbose_name="Código método SICAV")),
                ("method_snapshot", models.CharField(blank=True, max_length=80, verbose_name="Método de pago")),
                ("reference", models.CharField(blank=True, max_length=200, verbose_name="Referencia / operación")),
                ("status", models.CharField(choices=[("PENDING", "Pendiente"), ("REGISTERED", "Pagado"), ("VOIDED", "Anulado"), ("UNKNOWN", "Sin clasificar")], default="REGISTERED", max_length=20, verbose_name="Estado histórico")),
                ("issued_at", models.DateTimeField(blank=True, null=True, verbose_name="Emitido el")),
                ("paid_at", models.DateTimeField(blank=True, null=True, verbose_name="Pagado el")),
                ("registered_at", models.DateTimeField(blank=True, null=True, verbose_name="Registrado el")),
                ("due_date", models.DateField(blank=True, null=True, verbose_name="Vencimiento del cobro")),
                ("collector_snapshot", models.CharField(blank=True, max_length=180, verbose_name="Cobrador histórico")),
                ("registered_by_snapshot", models.CharField(blank=True, max_length=180, verbose_name="Usuario histórico")),
                ("note", models.TextField(blank=True, verbose_name="Observación")),
                ("is_validated", models.BooleanField(default=False, verbose_name="Validado")),
                ("validation_notes", models.TextField(blank=True, verbose_name="Notas de validación")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="legacy_payment_snapshots", to="organization.branch", verbose_name="Sede")),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="legacy_payment_snapshots", to="customers.customer", verbose_name="Abonado")),
            ],
            options={
                "verbose_name": "Pago histórico SICAV",
                "verbose_name_plural": "Pagos históricos SICAV",
                "ordering": ["-paid_at", "-issued_at", "-pk"],
            },
        ),
        migrations.CreateModel(
            name="LegacyPaymentAllocationSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.01"))], verbose_name="Monto aplicado")),
                ("discount", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=10, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.00"))], verbose_name="Descuento")),
                ("notes", models.CharField(blank=True, max_length=240, verbose_name="Observación")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("charge", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="legacy.legacychargesnapshot", verbose_name="Cargo histórico")),
                ("payment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="allocations", to="legacy.legacypaymentsnapshot", verbose_name="Pago histórico")),
            ],
            options={
                "verbose_name": "Aplicación de pago histórica",
                "verbose_name_plural": "Aplicaciones de pago históricas",
                "ordering": ["payment", "pk"],
            },
        ),
        migrations.AddConstraint(
            model_name="legacypaymentallocationsnapshot",
            constraint=models.UniqueConstraint(fields=("payment", "charge"), name="legacy_unique_payment_charge_allocation"),
        ),
        migrations.CreateModel(
            name="LegacyReceiptSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_snapshot", models.CharField(max_length=120, verbose_name="Documento")),
                ("series", models.CharField(blank=True, max_length=20, verbose_name="Serie")),
                ("number", models.CharField(blank=True, max_length=40, verbose_name="Número")),
                ("document_type_snapshot", models.CharField(blank=True, max_length=100, verbose_name="Tipo de documento")),
                ("issuer_snapshot", models.CharField(blank=True, max_length=180, verbose_name="Emisor")),
                ("taxable_base", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.00"))], verbose_name="Base gravada")),
                ("igv_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.00"))], verbose_name="IGV")),
                ("exempt_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.00"))], verbose_name="Importe exonerado")),
                ("other_tax_amount", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=10, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.00"))], verbose_name="Otros tributos")),
                ("total", models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.01"))], verbose_name="Total documento")),
                ("issued_at", models.DateTimeField(blank=True, null=True, verbose_name="Emitido el")),
                ("pdf_file", models.FileField(blank=True, upload_to="legacy/receipts/new/pdf/", verbose_name="PDF histórico")),
                ("xml_file", models.FileField(blank=True, upload_to="legacy/receipts/new/xml/", verbose_name="XML histórico")),
                ("legacy_pdf_reference", models.CharField(blank=True, max_length=500, verbose_name="Referencia PDF SICAV")),
                ("legacy_xml_reference", models.CharField(blank=True, max_length=500, verbose_name="Referencia XML SICAV")),
                ("is_validated", models.BooleanField(default=False, verbose_name="Validado")),
                ("validation_notes", models.TextField(blank=True, verbose_name="Notas de validación")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("payment", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="receipt", to="legacy.legacypaymentsnapshot", verbose_name="Pago histórico")),
            ],
            options={
                "verbose_name": "Comprobante histórico SICAV",
                "verbose_name_plural": "Comprobantes históricos SICAV",
                "ordering": ["-issued_at", "-pk"],
            },
        ),
    ]
