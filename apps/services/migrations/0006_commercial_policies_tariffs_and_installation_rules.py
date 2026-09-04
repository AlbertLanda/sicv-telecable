import datetime
from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


def seed_billing_policies(apps, schema_editor):
    BillingPolicy = apps.get_model("services", "BillingPolicy")

    policies = [
        {
            "code": "CALENDAR_PP5",
            "name": "Mes calendario - pronto pago S/ 5",
            "billing_mode": "CALENDAR_MONTH",
            "discount_amount": Decimal("5.00"),
            "discount_deadline_day": 29,
            "cut_day_next_month": 6,
            "first_month_required": True,
        },
        {
            "code": "ANNIVERSARY_PP10",
            "name": "Aniversario - pronto pago S/ 10",
            "billing_mode": "ANNIVERSARY",
            "discount_amount": Decimal("10.00"),
            "discount_days_before_due": 3,
            "cut_days_after_due": 1,
            "first_month_required": True,
        },
        {
            "code": "CALENDAR_NO_DISCOUNT",
            "name": "Mes calendario - sin pronto pago",
            "billing_mode": "CALENDAR_MONTH",
            "discount_amount": Decimal("0.00"),
            "cut_day_next_month": 6,
            "first_month_required": True,
        },
    ]

    for data in policies:
        BillingPolicy.objects.get_or_create(code=data["code"], defaults=data)


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0002_seed_sedes_reales"),
        ("services", "0005_subscriptionannexadjustment"),
        ("work_orders", "0014_seed_tv_annex_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="BillingPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=40, unique=True, verbose_name="Código")),
                ("name", models.CharField(max_length=120, verbose_name="Política de cobro")),
                ("billing_mode", models.CharField(choices=[("CALENDAR_MONTH", "Mes calendario"), ("ANNIVERSARY", "Aniversario de instalación")], max_length=20, verbose_name="Modalidad de vencimiento")),
                ("discount_amount", models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Descuento por pronto pago")),
                ("discount_deadline_day", models.PositiveSmallIntegerField(blank=True, help_text="Para mes calendario. Si el mes es más corto, se usa su último día.", null=True, verbose_name="Día límite de pronto pago")),
                ("discount_days_before_due", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Días antes del vencimiento para pronto pago")),
                ("cut_day_next_month", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Día de corte del mes siguiente")),
                ("cut_days_after_due", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Días después del vencimiento para corte")),
                ("first_month_required", models.BooleanField(default=True, verbose_name="Exige primera mensualidad al instalar")),
                ("is_active", models.BooleanField(default=True, verbose_name="Activo")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Política de cobro", "verbose_name_plural": "Políticas de cobro", "ordering": ["name"]},
        ),
        migrations.AddField(
            model_name="plan",
            name="generation",
            field=models.PositiveSmallIntegerField(blank=True, help_text="Año comercial del plan, por ejemplo 2024, 2025 o 2026.", null=True, verbose_name="Generación"),
        ),
        migrations.AddField(
            model_name="plan",
            name="commercial_category",
            field=models.CharField(blank=True, choices=[("STANDARD", "Estándar"), ("ECONOMIC", "Económico"), ("SUPER_ECONOMIC", "Súper económico")], max_length=20, verbose_name="Categoría comercial"),
        ),
        migrations.AddField(
            model_name="plan",
            name="requires_geographic_tariff",
            field=models.BooleanField(default=False, help_text="Active esta opción cuando instalación o mensualidad dependen de la ubicación, como ocurre con Cable.", verbose_name="Requiere tarifa por sede/zona"),
        ),
        migrations.AddField(
            model_name="plan",
            name="billing_policy",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="plans", to="services.billingpolicy", verbose_name="Política de cobro"),
        ),
        migrations.AlterField(
            model_name="plan",
            name="monthly_price",
            field=models.DecimalField(decimal_places=2, default=0, help_text="Se usa como respaldo cuando el plan no requiere tarifa geográfica. La tarifa por sede/zona prevalece cuando existe.", max_digits=10, verbose_name="Precio mensual referencial"),
        ),
        migrations.AlterField(
            model_name="plan",
            name="included_tv_points",
            field=models.PositiveIntegerField(default=0, help_text="La cortesía solo puede utilizarse durante la instalación inicial. Una TV no utilizada ese día no queda pendiente para el futuro.", verbose_name="Máximo de TV de cortesía en instalación inicial"),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="billing_cycle",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="Ciclo de facturación legado"),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="annex_count",
            field=models.PositiveIntegerField(default=0, help_text="Cantidad de puntos de TV adicionales que generan cargo mensual.", verbose_name="Anexos de TV activos"),
        ),
        migrations.AddField(
            model_name="subscription",
            name="base_installation_fee",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Instalación base contratada"),
        ),
        migrations.AddField(
            model_name="subscription",
            name="base_monthly_fee",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Mensualidad base contratada"),
        ),
        migrations.AddField(
            model_name="subscription",
            name="initial_tv_courtesy_granted",
            field=models.PositiveIntegerField(default=0, help_text="Es un dato histórico. Las cortesías no utilizadas durante el alta no quedan disponibles para una instalación futura.", verbose_name="TV de cortesía otorgadas en instalación inicial"),
        ),
        migrations.AddField(
            model_name="subscription",
            name="billing_policy",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="subscriptions", to="services.billingpolicy", verbose_name="Política de cobro contratada"),
        ),
        migrations.CreateModel(
            name="PlanTariff",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("installation_fee", models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Costo de instalación")),
                ("monthly_fee", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Mensualidad normal")),
                ("valid_from", models.DateField(default=datetime.date.today, verbose_name="Vigente desde")),
                ("valid_until", models.DateField(blank=True, null=True, verbose_name="Vigente hasta")),
                ("is_active", models.BooleanField(default=True, verbose_name="Activo")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="plan_tariffs", to="organization.branch", verbose_name="Sede")),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tariffs", to="services.plan", verbose_name="Plan")),
                ("zone", models.ForeignKey(blank=True, help_text="Vacío significa que aplica a toda la sede salvo una tarifa más específica.", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="plan_tariffs", to="organization.zone", verbose_name="Zona")),
            ],
            options={"verbose_name": "Tarifa de plan", "verbose_name_plural": "Tarifas de planes", "ordering": ["plan", "branch", "zone", "-valid_from"]},
        ),
        migrations.AddField(
            model_name="subscription",
            name="tariff",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="subscriptions", to="services.plantariff", verbose_name="Tarifa aplicada"),
        ),
        migrations.CreateModel(
            name="CommercialCoverageRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("generation", models.PositiveSmallIntegerField(verbose_name="Generación")),
                ("commercial_category", models.CharField(choices=[("STANDARD", "Estándar"), ("ECONOMIC", "Económico"), ("SUPER_ECONOMIC", "Súper económico")], max_length=20, verbose_name="Categoría comercial")),
                ("availability", models.CharField(choices=[("ALLOWED", "Permitido"), ("RECOMMENDED", "Recomendado"), ("REQUIRED", "Obligatorio"), ("NOT_AVAILABLE", "No disponible")], default="ALLOWED", max_length=20, verbose_name="Regla comercial")),
                ("valid_from", models.DateField(default=datetime.date.today, verbose_name="Vigente desde")),
                ("valid_until", models.DateField(blank=True, null=True, verbose_name="Vigente hasta")),
                ("is_active", models.BooleanField(default=True, verbose_name="Activo")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="commercial_coverage_rules", to="organization.branch", verbose_name="Sede")),
                ("zone", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="commercial_coverage_rules", to="organization.zone", verbose_name="Zona")),
            ],
            options={"verbose_name": "Regla comercial de cobertura", "verbose_name_plural": "Reglas comerciales de cobertura", "ordering": ["-generation", "branch", "zone", "commercial_category"]},
        ),
        migrations.CreateModel(
            name="InstallationMaterialRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("material", models.CharField(choices=[("UTP", "Cable UTP"), ("RG6", "Cable coaxial RG6"), ("DROP", "Fibra óptica Drop")], max_length=10, verbose_name="Material")),
                ("free_meters", models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Metros incluidos")),
                ("excess_price_per_meter", models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Precio por metro excedente")),
                ("valid_from", models.DateField(default=datetime.date.today, verbose_name="Vigente desde")),
                ("valid_until", models.DateField(blank=True, null=True, verbose_name="Vigente hasta")),
                ("is_active", models.BooleanField(default=True, verbose_name="Activo")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(blank=True, help_text="Vacío significa que la regla aplica a todas las sedes.", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="installation_material_rules", to="organization.branch", verbose_name="Sede")),
                ("service_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="installation_material_rules", to="services.servicetype", verbose_name="Tipo de servicio")),
            ],
            options={"verbose_name": "Regla de metraje de instalación", "verbose_name_plural": "Reglas de metraje de instalación", "ordering": ["material", "service_type", "branch", "-valid_from"]},
        ),
        migrations.CreateModel(
            name="InstallationMaterialUsage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("meters_used", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Metros utilizados")),
                ("free_meters_snapshot", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Metros incluidos aplicados")),
                ("excess_price_per_meter_snapshot", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Precio aplicado por metro excedente")),
                ("excess_meters", models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Metros excedentes")),
                ("excess_charge", models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name="Cobro por exceso")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("rule", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="usages", to="services.installationmaterialrule", verbose_name="Regla aplicada")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="installation_material_usages", to="work_orders.workorder", verbose_name="Orden de trabajo")),
            ],
            options={"verbose_name": "Metraje utilizado en instalación", "verbose_name_plural": "Metrajes utilizados en instalaciones", "ordering": ["work_order", "rule__material"]},
        ),
        migrations.AddConstraint(
            model_name="installationmaterialusage",
            constraint=models.UniqueConstraint(fields=("work_order", "rule"), name="unique_material_rule_per_work_order"),
        ),
        migrations.RunPython(seed_billing_policies, migrations.RunPython.noop),
    ]
