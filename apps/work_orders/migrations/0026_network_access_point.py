from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("work_orders", "0025_remove_incidentdetail_mac_remove_incidentdetail_nap_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="NetworkAccessPoint",
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
                    "legacy_id",
                    models.PositiveIntegerField(
                        blank=True,
                        null=True,
                        unique=True,
                        verbose_name="ID sistema anterior",
                    ),
                ),
                ("code", models.CharField(max_length=40, verbose_name="Código NAP")),
                ("name", models.CharField(max_length=220, verbose_name="Nombre NAP")),
                ("is_active", models.BooleanField(default=True, verbose_name="Activo")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="network_access_points",
                        to="organization.branch",
                        verbose_name="Sede",
                    ),
                ),
            ],
            options={
                "verbose_name": "NAP",
                "verbose_name_plural": "NAP",
                "ordering": ["branch", "name"],
                "indexes": [
                    models.Index(
                        fields=["branch", "is_active"],
                        name="nap_branch_active_idx",
                    ),
                    models.Index(fields=["code"], name="nap_code_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("branch", "code"),
                        name="unique_nap_code_per_branch",
                    ),
                ],
            },
        ),
    ]
