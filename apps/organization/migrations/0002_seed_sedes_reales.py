from django.db import migrations


# Sedes reales del despliegue FTTH, tal como se acordó con Joleydi:
# La Oroya, Jauja y Huancayo. Se seedean por migración (no por fixture
# ni por comando manual) para que cualquier entorno que corra
# `migrate` desde cero — el suyo, el de otro colaborador, o el de CI —
# termine con exactamente estas 3 sedes disponibles en el selector de
# "Datos generales" (Pantalla 4), sin depender de que alguien las
# cargue a mano por el admin.
SEDES_REALES = [
    {"code": "OROYA", "name": "La Oroya"},
    {"code": "JAUJA", "name": "Jauja"},
    {"code": "HUANCAYO", "name": "Huancayo"},
]


def seed_sedes_reales(apps, schema_editor):
    Branch = apps.get_model("organization", "Branch")

    for sede in SEDES_REALES:
        # get_or_create por "code" (campo único del modelo): si la
        # sede ya existe -por ejemplo, alguien ya la creó a mano desde
        # el admin- no se duplica ni se pisa el nombre que ya tenía.
        Branch.objects.get_or_create(
            code=sede["code"],
            defaults={
                "name": sede["name"],
                "is_active": True,
            },
        )


def eliminar_sedes_reales(apps, schema_editor):
    Branch = apps.get_model("organization", "Branch")

    Branch.objects.filter(
        code__in=[sede["code"] for sede in SEDES_REALES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            seed_sedes_reales,
            reverse_code=eliminar_sedes_reales,
        ),
    ]