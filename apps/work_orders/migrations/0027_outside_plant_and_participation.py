import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("technicians", "0001_initial"),
        ("work_orders", "0026_network_access_point"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workorder",
            name="subscription",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="work_orders",
                to="services.subscription",
                verbose_name="Suscripción",
            ),
        ),
        migrations.CreateModel(
            name="OutsidePlantDetail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("origin", models.CharField(choices=[("ATC", "ATC"), ("NOC", "NOC")], max_length=10, verbose_name="Origen")),
                ("route", models.CharField(max_length=220, verbose_name="Vía / tramo")),
                ("reference", models.CharField(blank=True, max_length=220, verbose_name="Referencia")),
                ("latitude", models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True, verbose_name="Latitud")),
                ("longitude", models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True, verbose_name="Longitud")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("work_order", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="outside_plant_detail", to="work_orders.workorder", verbose_name="Orden de Planta Externa")),
            ],
            options={
                "verbose_name": "Detalle de Planta Externa",
                "verbose_name_plural": "Detalles de Planta Externa",
            },
        ),
        migrations.CreateModel(
            name="WorkOrderParticipation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(choices=[("FIELD", "Atención de campo"), ("NOC", "Atención NOC"), ("LIQUIDATION", "Declarado en liquidación")], max_length=20, verbose_name="Origen de participación")),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Inicio de participación")),
                ("ended_at", models.DateTimeField(blank=True, null=True, verbose_name="Fin de participación")),
                ("remarks", models.TextField(blank=True, verbose_name="Aporte / observación")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("recorded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="recorded_work_order_participations", to=settings.AUTH_USER_MODEL, verbose_name="Registrado por")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="work_order_participations", to=settings.AUTH_USER_MODEL, verbose_name="Participante")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participations", to="work_orders.workorder", verbose_name="Orden")),
            ],
            options={
                "verbose_name": "Participación en orden",
                "verbose_name_plural": "Participaciones en órdenes",
                "ordering": ["started_at", "pk"],
            },
        ),
        migrations.AddIndex(
            model_name="workorderparticipation",
            index=models.Index(fields=["work_order", "user"], name="wo_part_order_user_idx"),
        ),
        migrations.AddIndex(
            model_name="workorderparticipation",
            index=models.Index(fields=["work_order", "ended_at"], name="wo_part_active_idx"),
        ),
        migrations.AlterModelOptions(
            name="workorder",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("assign_workorder", "Puede asignar órdenes de trabajo a un técnico"),
                    ("start_workorder", "Puede iniciar la atención de órdenes de trabajo"),
                    ("cancel_workorder", "Puede anular órdenes de trabajo"),
                    ("view_incident", "Puede consultar incidencias NOC"),
                    ("start_incident", "Puede iniciar la atención de incidencias NOC"),
                    ("close_incident", "Puede finalizar incidencias NOC"),
                    ("create_outsideplant", "Puede registrar órdenes de Planta Externa"),
                    ("view_outsideplant", "Puede consultar órdenes de Planta Externa"),
                ],
                "verbose_name": "Orden de trabajo",
                "verbose_name_plural": "Órdenes de trabajo",
            },
        ),
    ]
