from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("work_orders", "0031_transfer_service_code_history"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="workorder",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    (
                        "assign_workorder",
                        "Puede asignar órdenes de trabajo a un técnico",
                    ),
                    (
                        "start_workorder",
                        "Puede iniciar la atención de órdenes de trabajo",
                    ),
                    (
                        "cancel_workorder",
                        "Puede anular órdenes de trabajo",
                    ),
                    (
                        "withdraw_installation",
                        "Puede registrar desistimientos de instalación",
                    ),
                    (
                        "view_incident",
                        "Puede consultar incidencias NOC",
                    ),
                    (
                        "start_incident",
                        "Puede iniciar la atención de incidencias NOC",
                    ),
                    (
                        "close_incident",
                        "Puede finalizar incidencias NOC",
                    ),
                    (
                        "create_outsideplant",
                        "Puede registrar órdenes de Planta Externa",
                    ),
                    (
                        "view_outsideplant",
                        "Puede consultar órdenes de Planta Externa",
                    ),
                ],
                "verbose_name": "Orden de trabajo",
                "verbose_name_plural": "Órdenes de trabajo",
            },
        ),
        migrations.CreateModel(
            name="InstallationWithdrawal",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "order_number",
                    models.CharField(
                        db_index=True,
                        max_length=30,
                        verbose_name="Orden retirada",
                    ),
                ),
                (
                    "branch_code",
                    models.CharField(
                        blank=True,
                        max_length=40,
                        verbose_name="Sede",
                    ),
                ),
                (
                    "released_customer_code",
                    models.CharField(
                        blank=True,
                        max_length=30,
                        verbose_name="Código de abonado liberado",
                    ),
                ),
                (
                    "released_service_code",
                    models.CharField(
                        blank=True,
                        max_length=80,
                        verbose_name="Código de servicio liberado",
                    ),
                ),
                (
                    "reason",
                    models.TextField(
                        verbose_name="Motivo del desistimiento",
                    ),
                ),
                (
                    "customer_deleted",
                    models.BooleanField(
                        default=False,
                        verbose_name="Alta de cliente eliminada",
                    ),
                ),
                (
                    "withdrawn_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Fecha de desistimiento",
                    ),
                ),
                (
                    "withdrawn_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="installation_withdrawals",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Registrado por",
                    ),
                ),
            ],
            options={
                "verbose_name": "Desistimiento de instalación",
                "verbose_name_plural": "Desistimientos de instalación",
                "ordering": ["-withdrawn_at", "-pk"],
            },
        ),
    ]
