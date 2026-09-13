"""El padrón real de talonarios: cuáles hay y de qué ventanilla se ofrecen.

Hasta aquí el sistema ofrecía la misma lista de talonarios se cobrara donde se
cobrara, y esa lista era la de una sola ventanilla -el Local Principal de
Jauja-. En el sistema que se reemplaza cada oficina tiene su propio juego de
blocks, porque un talonario es papel que está en un cajón concreto: ofrecer en
Apata un block que vive en Oroya invita a numerar algo que nadie tiene delante.

Tres cosas que el padrón deja claras y que el modelo tuvo que aprender:

1. **Un block se comparte entre oficinas.** «F:F001 - CABLE LOS ANDES» va por
   el 8323 en el Local Principal de Jauja, en la Oficina 2 y en Apata: es un
   solo talonario con un solo correlativo, ofrecido en tres sitios. Por eso la
   relación es muchos a muchos y no una fila por oficina, que daría tres
   correlativos para un block que es uno.

2. **La misma serie impresa puede ser dos talonarios distintos.** «B001» es
   CABLE LOS ANDES por el 41316 en Jauja y INVERSIONES por el 49217 en Oroya.
   No es el mismo block ni lleva la misma cuenta, así que son dos filas con
   códigos distintos que imprimen el mismo «B001». Es la misma razón por la
   que «S010» ya nombraba tres blocks.

3. **Cada oficina apila los suyos a su manera.** Los tres «S003» salen en
   Jauja Cajas como SPEEDY, VELOCIDAD, RED ÓPTICA y en Huancayo El Tambo como
   VELOCIDAD, RED ÓPTICA, SPEEDY. Por eso el orden viaja en la relación y no
   en el talonario, donde solo cabría una de las dos respuestas.

Los blocks de un cobrador (JU*, MR*, ST*) se ofrecen en **todas** las
oficinas: son papel que él lleva encima, no de una ventanilla, y por eso no
figuran en la lista de ninguna. Encabezan cada lista, como ya hacían en la
global.

El **depósito** de cada sede ofrece lo mismo que su local principal. No tiene
blocks propios -nadie está parado ahí-, pero es donde cae lo que llega por
banco, y dejarlo sin talonario habría impedido registrar una transferencia.

Los números anotados son el **próximo a imprimir**, así que `last_number` se
guarda uno por debajo. Y solo se adelanta, nunca se retrocede: si esta base ya
emitió más allá del número del padrón, volver atrás repetiría comprobantes ya
entregados.
"""

from django.db import migrations


BOLETA = "BOLETA DE VENTA ELECTRÓNICA"
FACTURA = "FACTURA ELECTRÓNICA"
RECIBO = "RECIBO DE SERVICIO PÚBLICO ELECTRÓNICO"


# Talonarios que el padrón añade.
#
# El código lleva sufijo cuando la serie impresa se repite con otro emisor o
# con otra línea: «B001» a secas ya existía y es el de CABLE LOS ANDES, así
# que el de INVERSIONES entra como «B001-INV». Los ocho que ya estaban
# conservan su código para no romper los comprobantes que cuelgan de ellos.
#
# código, serie impresa, emisor, etiqueta, próximo número, título
TALONARIOS_NUEVOS = [
    ("B001-INV", "B001", "INV", "B:B001 - INVERSIONES", 49217, BOLETA),
    ("B002-CLA", "B002", "CLA", "B:B002 - CABLE LOS ANDES", 6564, BOLETA),
    ("B003-CLA", "B003", "CLA", "B:B003 - CABLE LOS ANDES", 7958, BOLETA),
    ("B003-INV", "B003", "INV", "B:B003 - INVERSIONES", 38785, BOLETA),
    ("B004-CLA", "B004", "CLA", "B:B004 - CABLE LOS ANDES", 25751, BOLETA),
    ("B006-CLA", "B006", "CLA", "B:B006 - CABLE LOS ANDES", 2990, BOLETA),
    ("B006-INV", "B006", "INV", "B:B006 - INVERSIONES", 363, BOLETA),
    ("B007-INV", "B007", "INV", "B:B007 - INVERSIONES", 69, BOLETA),
    ("F001-INV", "F001", "INV", "F:F001 - INVERSIONES", 12070, FACTURA),
    ("F002-CLA", "F002", "CLA", "F:F002 - CABLE LOS ANDES", 178, FACTURA),
    ("F003-CLA", "F003", "CLA", "F:F003 - CABLE LOS ANDES", 2126, FACTURA),
    ("F004-CLA", "F004", "CLA", "F:F004 - CABLE LOS ANDES", 6, FACTURA),
    ("S002-VELOCIDAD", "S002", "SPQ", "S:S002 - VELOCIDAD", 5773, RECIBO),
    ("S002-RED-OPTICA", "S002", "SPQ", "S:S002 - RED OPTICA", 13251, RECIBO),
    ("S002-SPEEDY", "S002", "SPQ", "S:S002 - SPEEDY", 7555, RECIBO),
    ("S003-VELOCIDAD", "S003", "SPQ", "S:S003 - VELOCIDAD", 502, RECIBO),
    ("S003-RED-OPTICA", "S003", "SPQ", "S:S003 - RED OPTICA", 443, RECIBO),
    ("S003-SPEEDY", "S003", "SPQ", "S:S003 - SPEEDY", 735, RECIBO),
    ("S004-VELOCIDAD", "S004", "SPQ", "S:S004 - VELOCIDAD", 663, RECIBO),
    ("S008-RED-OPTICA", "S008", "SPQ", "S:S008 - RED OPTICA", 1, RECIBO),
    ("S008-SPEEDY", "S008", "SPQ", "S:S008 - SPEEDY", 171, RECIBO),
    ("S009-RED-OPTICA", "S009", "SPQ", "S:S009 - RED OPTICA", 2060, RECIBO),
    ("S009-SPEEDY", "S009", "SPQ", "S:S009 - SPEEDY", 1863, RECIBO),
    ("S011-VELOCIDAD", "S011", "SPQ", "S:S011 - VELOCIDAD", 11953, RECIBO),
    ("S011-RED-OPTICA", "S011", "SPQ", "S:S011 - RED OPTICA", 15276, RECIBO),
    ("S011-SPEEDY", "S011", "SPQ", "S:S011 - SPEEDY", 23495, RECIBO),
    ("VCOND-INV", "V.COND", "INV", "V.COND - INVERSIONES", 15334, RECIBO),
]


# Los tres que ya existían y han seguido emitiendo desde que se sembraron.
# código -> próximo número según el padrón
CORRELATIVOS_AL_DIA = {
    "B001": 41316,
    "B002": 31985,
    "F002": 5599,
}


# Los blocks de un cobrador. Van en toda oficina y encabezan la lista: vienen
# numerados de papel, así que proponen el número en blanco.
BLOCKS_DE_COBRADOR = [
    "JU1", "JU2", "JU3",
    "MR3", "MR4",
    "ST1", "ST2", "ST3", "ST4", "ST5",
]


# Qué ofrece cada ventanilla, en el orden en que lo ofrece.
PADRON = {
    "JAUJA-PRINCIPAL": [
        "B001", "B002", "F001", "F002",
        "S010-VELOCIDAD", "S010-RED-OPTICA", "S010-SPEEDY",
        "VCOND",
    ],
    "JAUJA-OF2": [
        "B003-INV", "B004-CLA", "F001", "F002",
        "S011-VELOCIDAD", "S011-RED-OPTICA", "S011-SPEEDY",
        "VCOND",
    ],
    "JAUJA-CAJAS": [
        "B003-CLA", "F002-CLA",
        "S003-SPEEDY", "S003-VELOCIDAD", "S003-RED-OPTICA",
        "VCOND",
    ],
    "JAUJA-APATA": [
        "B006-CLA", "F001",
        "S008-SPEEDY", "S008-RED-OPTICA",
        "VCOND",
    ],
    "JAUJA-YAUYOS": [
        "VCOND",
    ],
    "HUANCAYO-ELTAMBO": [
        "B003-CLA", "B007-INV", "F002-CLA", "F002",
        "S003-VELOCIDAD", "S003-RED-OPTICA", "S003-SPEEDY",
        "VCOND",
    ],
    "HUANCAYO-SICAYA": [
        "B003-CLA", "B006-INV", "F002-CLA", "F002",
        "S004-VELOCIDAD", "S009-RED-OPTICA", "S009-SPEEDY",
        "VCOND",
    ],
    "OROYA-CARHUACOTO": [
        "B001-INV", "B002-CLA", "F001-INV", "F003-CLA", "F004-CLA",
        "S002-SPEEDY", "S002-RED-OPTICA", "S002-VELOCIDAD",
        "VCOND-INV",
    ],
    "OROYA-PRINCIPAL": [
        "B001-INV", "B002-CLA", "F001-INV", "F003-CLA",
        "S002-SPEEDY", "S002-VELOCIDAD", "S002-RED-OPTICA",
        "VCOND-INV",
    ],
    "OROYA-OF2": [
        "B001-INV", "B002-CLA", "F001-INV",
        "VCOND-INV",
    ],
}


# El depósito de cada sede ofrece lo del local principal de esa sede.
DEPOSITOS = {
    "JAUJA-DEPOSITO": "JAUJA-PRINCIPAL",
    "HUANCAYO-DEPOSITO": "HUANCAYO-ELTAMBO",
    "OROYA-DEPOSITO": "OROYA-PRINCIPAL",
}


# El primero de los que ya estaban va en la posición 11: del 1 al 10 están los
# blocks de cobrador y en la 0 el R001 retirado.
PRIMERA_POSICION_NUEVA = 19


def sembrar(apps, schema_editor):
    Issuer = apps.get_model("payments", "Issuer")
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")
    OfficeSequence = apps.get_model("payments", "OfficeSequence")
    Office = apps.get_model("organization", "Office")

    empresas = {issuer.code: issuer for issuer in Issuer.objects.all()}

    # --- Los talonarios nuevos -------------------------------------
    for orden, fila in enumerate(TALONARIOS_NUEVOS, start=PRIMERA_POSICION_NUEVA):
        code, series, emisor, label, proximo, titulo = fila

        ReceiptSequence.objects.update_or_create(
            code=code,
            defaults={
                "series": series,
                "issuer": empresas.get(emisor),
                "document_title": titulo,
                "label": label,
                "position": orden,
                "autonumber": True,
                "last_number": proximo - 1,
            },
        )

    # --- Los que ya estaban y han seguido emitiendo -----------------
    for code, proximo in CORRELATIVOS_AL_DIA.items():
        # Solo hacia adelante. Si esta base ya pasó de ahí, retroceder
        # repetiría números de comprobantes ya entregados.
        ReceiptSequence.objects.filter(
            code=code,
            last_number__lt=proximo - 1,
        ).update(last_number=proximo - 1)

    # --- El mapa oficina / talonario -------------------------------
    listas = dict(PADRON)

    for deposito, principal in DEPOSITOS.items():
        if principal in listas:
            listas[deposito] = listas[principal]

    talonarios = {
        sequence.code: sequence for sequence in ReceiptSequence.objects.all()
    }

    for office in Office.objects.all():
        propios = listas.get(office.code)

        # Una oficina que el padrón no nombra se queda sin lista propia y
        # cae a la lista completa al cobrar. Inventarle un juego de blocks
        # sería decidir por la ventanilla qué papel tiene en el cajón.
        if propios is None:
            continue

        orden = 0

        for code in BLOCKS_DE_COBRADOR + list(propios):
            sequence = talonarios.get(code)

            if sequence is None:
                continue

            orden += 1

            OfficeSequence.objects.update_or_create(
                office=office,
                sequence=sequence,
                defaults={"position": orden},
            )


def vaciar(apps, schema_editor):
    """Deshacer suelta el mapa y los talonarios que no llegaron a emitir.

    Los correlativos que se adelantaron **no** vuelven atrás: si mientras
    tanto salió algún comprobante, retroceder el contador lo repetiría.
    """
    ReceiptSequence = apps.get_model("payments", "ReceiptSequence")
    OfficeSequence = apps.get_model("payments", "OfficeSequence")

    OfficeSequence.objects.all().delete()

    ReceiptSequence.objects.filter(
        code__in=[fila[0] for fila in TALONARIOS_NUEVOS],
        receipts__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0004_office_is_deposit"),
        ("payments", "0011_talonarios_por_oficina"),
    ]

    operations = [
        migrations.RunPython(sembrar, vaciar),
    ]
