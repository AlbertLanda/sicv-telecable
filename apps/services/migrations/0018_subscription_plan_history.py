# Generated for editable historical subscription plans.

import decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0017_planes_sistema_anterior"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionPlanHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("service_name_snapshot", models.CharField(blank=True, max_length=120, verbose_name="Servicio histórico")),
                ("plan_name_snapshot", models.CharField(max_length=180, verbose_name="Plan histórico")),
                ("start_date", models.DateField(verbose_name="Vigente desde")),
                ("end_date", models.DateField(blank=True, null=True, verbose_name="Vigente hasta")),
                ("monthly_fee_snapshot", models.DecimalField(blank=True, decimal_places=2, help_text="Vacío significa que todavía no se ha validado el precio histórico. Cero se reserva para una tarifa realmente gratuita.", max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(decimal.Decimal("0.00"))], verbose_name="Mensualidad histórica")),
                ("billing_policy_name_snapshot", models.CharField(blank=True, max_length=120, verbose_name="Política histórica")),
                ("source", models.CharField(choices=[("NATIVE", "SICV"), ("SICAV", "SICAV")], default="NATIVE", max_length=20, verbose_name="Origen")),
                ("source_reference", models.CharField(blank=True, help_text="Ejemplo: contrato 8610 u orden de cambio de plan 103676.", max_length=120, verbose_name="Referencia de origen")),
                ("is_validated", models.BooleanField(default=False, verbose_name="Validado")),
                ("validation_notes", models.TextField(blank=True, verbose_name="Notas de validación")),
                ("validated_at", models.DateTimeField(blank=True, null=True, verbose_name="Validado el")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("billing_policy", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="subscription_plan_history", to="services.billingpolicy", verbose_name="Política normalizada")),
                ("plan", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="subscription_history", to="services.plan", verbose_name="Plan normalizado")),
                ("service_type", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="subscription_plan_history", to="services.servicetype", verbose_name="Servicio normalizado")),
                ("subscription", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="plan_history", to="services.subscription", verbose_name="Suscripción")),
                ("validated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="validated_subscription_plan_history", to=settings.AUTH_USER_MODEL, verbose_name="Validado por")),
            ],
            options={
                "verbose_name": "Historial de plan",
                "verbose_name_plural": "Historial de planes",
                "ordering": ["subscription", "start_date", "pk"],
            },
        ),
        migrations.AddIndex(
            model_name="subscriptionplanhistory",
            index=models.Index(fields=["subscription", "start_date"], name="svc_plan_hist_sub_start_idx"),
        ),
    ]
