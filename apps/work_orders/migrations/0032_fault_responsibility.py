import apps.work_orders.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("work_orders", "0031_transfer_service_code_history"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FaultDetail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("responsibility", models.CharField(choices=[("CUSTOMER", "Cliente"), ("COMPANY", "Empresa"), ("OTHER", "Otros")], default="COMPANY", max_length=20, verbose_name="Responsabilidad")),
                ("responsibility_note", models.TextField(blank=True, verbose_name="Sustento de la responsabilidad")),
                ("responsibility_source", models.CharField(choices=[("OPERATOR", "Operador"), ("TECHNICIAN", "Técnico")], default="OPERATOR", max_length=20, verbose_name="Registrada por")),
                ("responsibility_set_at", models.DateTimeField(blank=True, null=True, verbose_name="Registrada el")),
                ("service_fee_snapshot", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name="Atención de la avería")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("responsibility_set_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="fault_responsibilities_set", to=settings.AUTH_USER_MODEL, verbose_name="Usuario que la registró")),
                ("work_order", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="fault_detail", to="work_orders.workorder", verbose_name="Orden de avería")),
            ],
            options={
                "verbose_name": "Detalle de avería",
                "verbose_name_plural": "Detalles de avería",
            },
        ),
        migrations.CreateModel(
            name="FaultResponsibilityEvidence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to=apps.work_orders.models.fault_evidence_upload_path, verbose_name="Archivo o fotografía")),
                ("source", models.CharField(choices=[("OPERATOR", "Operador"), ("TECHNICIAN", "Técnico")], max_length=20, verbose_name="Adjuntada por")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de carga")),
                ("fault_detail", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evidences", to="work_orders.faultdetail", verbose_name="Detalle de avería")),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="fault_responsibility_evidences", to=settings.AUTH_USER_MODEL, verbose_name="Usuario")),
            ],
            options={
                "verbose_name": "Evidencia de responsabilidad",
                "verbose_name_plural": "Evidencias de responsabilidad",
                "ordering": ["-created_at", "-pk"],
            },
        ),
    ]
