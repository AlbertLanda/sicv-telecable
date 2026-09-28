from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organization", "0004_office_is_deposit"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditEvent",
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
                ("method", models.CharField(max_length=10, verbose_name="Método")),
                (
                    "route_name",
                    models.CharField(
                        blank=True,
                        max_length=180,
                        verbose_name="Ruta lógica",
                    ),
                ),
                ("path", models.CharField(max_length=500, verbose_name="Ruta")),
                (
                    "status_code",
                    models.PositiveSmallIntegerField(
                        default=200,
                        verbose_name="Estado HTTP",
                    ),
                ),
                (
                    "description",
                    models.CharField(max_length=240, verbose_name="Actividad"),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Fecha y hora",
                    ),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audit_events",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuario",
                    ),
                ),
                (
                    "branch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audit_events",
                        to="organization.branch",
                        verbose_name="Sede",
                    ),
                ),
            ],
            options={
                "verbose_name": "Evento de auditoría",
                "verbose_name_plural": "Eventos de auditoría",
                "ordering": ["-created_at", "-pk"],
            },
        ),
        migrations.AddIndex(
            model_name="auditevent",
            index=models.Index(fields=["-created_at"], name="audit_event_created_idx"),
        ),
        migrations.AddIndex(
            model_name="auditevent",
            index=models.Index(
                fields=["actor", "-created_at"],
                name="audit_actor_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="auditevent",
            index=models.Index(
                fields=["branch", "-created_at"],
                name="audit_branch_created_idx",
            ),
        ),
    ]
