
from django.db import migrations


DIRECCION = "Av. Huancayo Nº215 - Jauja"
TELEFONO = "064 466080"

# Las que ya existían y estrenan RUC. Con lo anterior al lado, para deshacer.
CORREGIDAS = {
    "CLA": (
        {"business_name": "CABLE LOS ANDES S.A.C.", "ruc": "20603086431"},
        {"business_name": "CABLE LOS ANDES E.I.R.L.", "ruc": "20000000001"},
    ),
    "SPQ": (
        {"business_name": "SPEEDY QUANTICO E.I.R.L.", "ruc": "20610526455"},
        {"business_name": "SPEEDY QUANTICO E.I.R.L.", "ruc": "20000000003"},
    ),
}

# Las que se dan de alta, con los talonarios que les pasan.
NUEVAS = [
    (
        "VEL",
        "VELOCIDAD DE LOS ANDES EIRL",
        "20609510103",
        [
            "S002-VELOCIDAD",
            "S003-VELOCIDAD",
            "S004-VELOCIDAD",
            "S010-VELOCIDAD",
            "S011-VELOCIDAD",
        ],
    ),
    (
        "ROP",
        "RED OPTICA E.I.R.L.",
        "20610540369",
        [
            "S002-RED-OPTICA",
            "S003-RED-OPTICA",
            "S008-RED-OPTICA",
            "S009-RED-OPTICA",
            "S010-RED-OPTICA",
            "S011-RED-OPTICA",
        ],
    ),
]


def aplicar(apps, schema_editor):
    Issuer = apps.get_model("payments", "Issuer")
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")

    for code, (ahora, _antes) in CORREGIDAS.items():
        Issuer.objects.filter(code=code).update(**ahora)

    for code, business_name, ruc, talonarios in NUEVAS:
        empresa, _ = Issuer.objects.update_or_create(
            code=code,
            defaults={
                "business_name": business_name,
                "ruc": ruc,
                "address": DIRECCION,
                "phone": TELEFONO,
            },
        )

        ReceiptSequence.objects.filter(code__in=talonarios).update(
            issuer=empresa
        )


def deshacer(apps, schema_editor):
    Issuer = apps.get_model("payments", "Issuer")
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")

    for code, (_ahora, antes) in CORREGIDAS.items():
        Issuer.objects.filter(code=code).update(**antes)

    # Los talonarios vuelven a SPEEDY QUANTICO, que es de donde salieron.
    speedy = Issuer.objects.filter(code="SPQ").first()

    for code, _business_name, _ruc, talonarios in NUEVAS:
        ReceiptSequence.objects.filter(code__in=talonarios).update(
            issuer=speedy
        )
        Issuer.objects.filter(code=code).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0015_compromiso_con_cuotas"),
    ]

    operations = [
        migrations.RunPython(aplicar, deshacer),
    ]
