import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_profiles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    TechnicianProfile = apps.get_model("technicians", "TechnicianProfile")

    for user in User.objects.filter(role="TECHNICIAN").iterator():
        TechnicianProfile.objects.get_or_create(
            user=user,
            defaults={"area": "INTERNAL_NETWORK"},
        )


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TechnicianProfile",
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
                    "area",
                    models.CharField(
                        choices=[
                            ("INTERNAL_NETWORK", "Red interna"),
                            ("PEX", "Planta Externa"),
                        ],
                        default="INTERNAL_NETWORK",
                        max_length=30,
                        verbose_name="Cuadrilla / especialidad",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="technician_profile",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Técnico",
                    ),
                ),
            ],
            options={
                "verbose_name": "Perfil técnico",
                "verbose_name_plural": "Perfiles técnicos",
            },
        ),
        migrations.RunPython(backfill_profiles, migrations.RunPython.noop),
    ]
}
