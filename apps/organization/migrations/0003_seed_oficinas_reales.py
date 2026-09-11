from django.db import migrations


# Oficinas reales de cada sede, tal como las lista el sistema que se
# reemplaza. Se seedean por migración y no a mano por el admin, mismo
# criterio que las sedes de 0002: el selector de la barra superior no
# aparece si no hay ninguna, así que un entorno recién migrado se
# quedaba sin poder elegir dónde se cobra.
#
# El «Depósito» de cada sede es una oficina más a propósito. El dinero
# que llega por transferencia, Yape o depósito no lo recibe nadie en
# mostrador, pero sí cae en una sede concreta, y la cobranza tiene que
# poder decir dónde entró. Modelarlo aparte -un booleano «entró por
# banco»- obligaría a preguntar dos cosas para responder una.
OFICINAS_REALES = [
    ("JAUJA", "JAUJA-PRINCIPAL", "Local Principal"),
    ("JAUJA", "JAUJA-OF2", "Oficina 2"),
    ("JAUJA", "JAUJA-CAJAS", "Oficina Cajas"),
    ("JAUJA", "JAUJA-APATA", "Of. Apata"),
    ("JAUJA", "JAUJA-YAUYOS", "Of. Yauyos"),
    ("JAUJA", "JAUJA-DEPOSITO", "Deposito"),

    ("HUANCAYO", "HUANCAYO-SICAYA", "Sicaya"),
    ("HUANCAYO", "HUANCAYO-ELTAMBO", "Of. El Tambo"),
    ("HUANCAYO", "HUANCAYO-DEPOSITO", "Deposito"),

    ("OROYA", "OROYA-PRINCIPAL", "Local principal"),
    ("OROYA", "OROYA-OF2", "Oficina 2"),
    ("OROYA", "OROYA-CARHUACOTO", "Carhuacoto"),
    ("OROYA", "OROYA-DEPOSITO", "Deposito"),
]


def seed_oficinas(apps, schema_editor):
    Branch = apps.get_model("organization", "Branch")
    Office = apps.get_model("organization", "Office")

    sedes = {branch.code: branch for branch in Branch.objects.all()}

    for branch_code, code, name in OFICINAS_REALES:
        branch = sedes.get(branch_code)

        # Una sede que no está no detiene la migración: el despliegue
        # que solo tenga Huancayo se queda con las de Huancayo.
        if branch is None:
            continue

        Office.objects.get_or_create(
            code=code,
            defaults={
                "branch": branch,
                "name": name,
                "is_active": True,
            },
        )


def eliminar_oficinas(apps, schema_editor):
    Office = apps.get_model("organization", "Office")

    Office.objects.filter(
        code__in=[code for _, code, _ in OFICINAS_REALES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0002_seed_sedes_reales"),
    ]

    operations = [
        migrations.RunPython(seed_oficinas, eliminar_oficinas),
    ]
