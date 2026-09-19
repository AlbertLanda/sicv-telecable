"""Siembra el catálogo de conceptos cobrables del sistema anterior.

La lista es la que el operador tiene delante en la ventanilla: planes,
publicidad, alquileres, transporte de datos y los ajustes de caja. Entra por
migración y no por un comando suelto para que toda instalación -la del
servidor, la del que recién clona el repo, la de las pruebas- arranque con el
mismo desplegable.

La familia de cada uno se deduce de su nombre, que es como está organizada la
lista: todo lo que se cobra mes a mes -un plan de internet, un alquiler de
fibra, un enlace- responde como mensualidad; instalación, anexo y reconexión
tienen la suya; el resto -materiales, traslados, saldos, publicidad suelta-
cae en «otro concepto», que es el que no exige periodo ni se prorratea.

Se siembra sin tocar lo que ya exista: si alguien corrigió un nombre o dio de
baja un concepto desde el admin, volver a correr las migraciones no lo pisa.
"""

from django.db import migrations
from django.utils.text import slugify


CONCEPTOS = [
    "ALQUILER FIBRA ÓPTICA",
    "ALQUILER FIBRA ÓPTICA OSCURA",
    "ALQUILER FIBRA ÓPTICA OSCURA 100KM",
    "ALQUILER TERRENO",
    "ANEXO",
    "ANEXO DUO",
    "ANEXO FTTH",
    "APP ESTANDAR",
    "APP PREMIUM",
    "APP PREMIUM PLUS",
    "APP TELECABLE",
    "ARRENDAMIENTO FIBRA OSCURA ELECTROCENTRO",
    "ARRENDAMIENTO FIBRA OSCURA XIRRUS TEC",
    "AVERÍA CLIENTE",
    "CABLE ADICIONAL",
    "COSTO DE EQUIPAMIENTO",
    "CUOTA ROUTER",
    "DSCTO PROMOCION",
    "DUO ECONÓMICO",
    "DUO ECONÓMICO 100MG",
    "DUO ECONÓMICO 200MG",
    "DUO RESIDENCIAL 1000MG",
    "DUO RESIDENCIAL 100MBPS",
    "DUO RESIDENCIAL 100MG",
    "DUO RESIDENCIAL 1200MG",
    "DUO RESIDENCIAL 150MBPS",
    "DUO RESIDENCIAL 200MG",
    "DUO RESIDENCIAL 300MG",
    "DUO RESIDENCIAL 400MG",
    "DUO RESIDENCIAL 600MG",
    "DUO RESIDENCIAL 70MBPS",
    "DUO RESIDENCIAL 800MG",
    "ENLACE LAN2 LAN AGENCIA CAJA HUANCAYO",
    "INSTALACION INTERNET",
    "INSTALACIÓN",
    "INSTALACIÓN DE ANEXOS",
    "INSTALACIÓN RED MESH",
    "INSTALACIÓN SERVICIO HD",
    "INTERNET 1000MG",
    "INTERNET 100MG",
    "INTERNET 100MG UGEL",
    "INTERNET 10MG",
    "INTERNET 110MG",
    "INTERNET 1200MG",
    "INTERNET 12MG",
    "INTERNET 15MG",
    "INTERNET 16MG",
    "INTERNET 1MG",
    "INTERNET 200MG",
    "INTERNET 200MG UGEL",
    "INTERNET 20MG",
    "INTERNET 250MG",
    "INTERNET 260MG",
    "INTERNET 2MG",
    "INTERNET 300MG",
    "INTERNET 30MG",
    "INTERNET 3MG",
    "INTERNET 400MG",
    "INTERNET 40MG",
    "INTERNET 4MG",
    "INTERNET 500MG",
    "INTERNET 50MG",
    "INTERNET 5MG",
    "INTERNET 600MG",
    "INTERNET 60MG",
    "INTERNET 6MG",
    "INTERNET 70MG",
    "INTERNET 800MG",
    "INTERNET 80MG",
    "INTERNET 8MG",
    "INTERNET 8MG NEGOCIO",
    "INTERNET 90MG",
    "INTERNET CORPORATIVO 1.1GB M&A",
    "INTERNET CORPORATIVO 1.25 GB GIGARED TAMBO",
    "INTERNET CORPORATIVO 1.5GB TELSA",
    "INTERNET CORPORATIVO 100 MG",
    "INTERNET CORPORATIVO 1000MG",
    "INTERNET CORPORATIVO 100MG UGEL",
    "INTERNET CORPORATIVO 10MG SIMÉTRICO HUARIPAMPA",
    "INTERNET CORPORATIVO 1200MG",
    "INTERNET CORPORATIVO 1300MG",
    "INTERNET CORPORATIVO 15 MB NAJAH",
    "INTERNET CORPORATIVO 1500MG",
    "INTERNET CORPORATIVO 150MG MUNICIPALIDAD DE JAUJA",
    "INTERNET CORPORATIVO 1GB CREDIMAS GRUPO OSORES",
    "INTERNET CORPORATIVO 1GB M&A",
    "INTERNET CORPORATIVO 1GB TELSA",
    "INTERNET CORPORATIVO 2 GB GIGARED TAMBO",
    "INTERNET CORPORATIVO 2000MG",
    "INTERNET CORPORATIVO 200MBPS",
    "INTERNET CORPORATIVO 200MG",
    "INTERNET CORPORATIVO 20MG M&A",
    "INTERNET CORPORATIVO 20MG SIMETRICO HUARIPAMPA",
    "INTERNET CORPORATIVO 250MG GIGARED",
    "INTERNET CORPORATIVO 2GB CREDIMAS GRUPO OSORES",
    "INTERNET CORPORATIVO 30 MBPS",
    "INTERNET CORPORATIVO 300MG",
    "INTERNET CORPORATIVO 40MG LUCARBAL RENT A CAR",
    "INTERNET CORPORATIVO 500MG GIGARED",
    "INTERNET CORPORATIVO 50MG",
    "INTERNET CORPORATIVO 50MG UGEL",
    "INTERNET CORPORATIVO 5MG SIMÉTRICO HUARIPAMPA",
    "INTERNET CORPORATIVO 7MG SIMÉTRICO HUARIPAMPA",
    "INTERNET CORPORATIVO CORPORACIÓN GIGA 1100 MG 2026",
    "INTERNET CORPORATIVO CORPORACIÓN GIGA 300 MG",
    "INTERNET CORPORATIVO CORPORACIÓN GIGA 700 MG 2026",
    "INTERNET CORPORATIVO ECOSEM 100MG",
    "INTERNET CORPORATIVO HOTEL TUNANMARCA",
    "INTERNET CORPORATIVO INTERCONEXION TV",
    "INTERNET CORPORATIVO UNTEL 500 MG",
    "INTERNET CORPORATIVO VOLVO",
    "INTERNET DUO 100MG",
    "INTERNET DUO 10MG",
    "INTERNET DUO 12MG",
    "INTERNET DUO 15MG",
    "INTERNET DUO 16MG",
    "INTERNET DUO 1MG",
    "INTERNET DUO 20MG",
    "INTERNET DUO 2MG",
    "INTERNET DUO 30MG",
    "INTERNET DUO 3MG",
    "INTERNET DUO 40MG",
    "INTERNET DUO 4MG",
    "INTERNET DUO 50MG",
    "INTERNET DUO 60MG",
    "INTERNET DUO 6MG",
    "INTERNET DUO 70MG",
    "INTERNET DUO 80MG",
    "INTERNET DUO 8MG",
    "INTERNET DUO 90MG",
    "INTERNET DUO ECONÓMICO CHAPOPAMPA",
    "INTERNET DUO ECONÓMICO MARG. DERECHA",
    "INTERNET DUO FIBRA 100MG",
    "INTERNET DUO FIBRA 20MG",
    "INTERNET DUO FIBRA 40MG",
    "INTERNET DUO FIBRA 80MG",
    "INTERNET ECONÓMICO 100MG",
    "INTERNET ECONÓMICO 200MG",
    "INTERNET ECONÓMICO CHAPOPAMPA",
    "INTERNET ECONÓMICO MARG. DERECHA",
    "INTERNET ECONÓMICO MARG. DERECHA 50MG",
    "INTERNET FIBRA 100MG",
    "INTERNET FIBRA 16MG",
    "INTERNET FIBRA 20MG",
    "INTERNET FIBRA 40MG",
    "INTERNET FIBRA 80MG",
    "INTERNET PYME 1000MG",
    "INTERNET PYME 100MG",
    "INTERNET PYME 150MG",
    "INTERNET PYME 160MG",
    "INTERNET PYME 200MG",
    "INTERNET PYME 20MG",
    "INTERNET PYME 300MG",
    "INTERNET PYME 400MG",
    "INTERNET PYME 40MG",
    "INTERNET PYME 440MG",
    "INTERNET PYME 500MG",
    "INTERNET PYME 60MG",
    "INTERNET PYME 800MG",
    "INTERNET PYME 80MG",
    "INTERNET RDSVM 20MG",
    "INTERNET RESIDENCIAL 100MG",
    "INTERNET RESIDENCIAL 150MG",
    "INTERNET RESIDENCIAL 200MG",
    "INTERNET RESIDENCIAL 300MG",
    "INTERNET RESIDENCIAL 50MG",
    "INTERNET RESIDENCIAL 600MG",
    "INTERNET RESIDENCIAL 70MG",
    "INTERNET RESIDENCIAL DUO 100MG",
    "INTERNET RESIDENCIAL DUO 150MG",
    "INTERNET RESIDENCIAL DUO 200MG",
    "INTERNET RESIDENCIAL DUO 300MG",
    "INTERNET RESIDENCIAL DUO 70MG",
    "INTERNET RESIDENCIAL MUNICIPALIDADES 600 MG",
    "IP PÚBLICA",
    "IPTV BLACK",
    "IPTV BÁSICO",
    "IPTV ORO",
    "MATERIALES",
    "MENSUALIDAD",
    "MIGRACION POR CAMBIO DE PLAN",
    "OTROS",
    "PLAN DUO ESTANDAR 600MG",
    "PLAN DUO PREMIUM 800MG",
    "PLAN DUO PREMIUM PLUS 1000MG",
    "PLAN DUO TELECABLE 400MG",
    "PLAN ESPECIAL HOTEL MUQUIYAUYO CORPORACIÓN JEMAQUITA SAC",
    "PLAN INTERNET ESTANDAR 600MG",
    "PLAN INTERNET PREMIUM 800MG",
    "PLAN INTERNET PREMIUM PLUS 1000MG",
    "PLAN INTERNET TELECABLE 400MG",
    "PROMO2 DUO RESIDENCIAL 1000MG",
    "PROMO2 DUO RESIDENCIAL 100MG",
    "PROMO2 DUO RESIDENCIAL 200MG",
    "PROMO2 DUO RESIDENCIAL 400MG",
    "PROMO2 DUO RESIDENCIAL 600MG",
    "PROMO2 DUO RESIDENCIAL 800MG",
    "PROMO2 INTERNET 1000MG",
    "PROMO2 INTERNET 100MG",
    "PROMO2 INTERNET 200MG",
    "PROMO2 INTERNET 400MG",
    "PROMO2 INTERNET 600MG",
    "PROMO2 INTERNET 800MG",
    "PUBLICIDAD",
    "PUBLICIDAD -- ANFITRIONAJE",
    "PUBLICIDAD -- BANNER",
    "PUBLICIDAD -- CINTILLO",
    "PUBLICIDAD -- EMISIÓN DE PUBLICIDAD",
    "PUBLICIDAD -- ENTREVISTA",
    "PUBLICIDAD -- EVENTOS",
    "PUBLICIDAD -- GRABACIÓN DE SPOT PARA USO PUBLICITARIO",
    "PUBLICIDAD -- GRABACIÓN DE SPOT PUBLICITARO CON VOZ",
    "PUBLICIDAD -- GRABACIÓN DE SPOT PUBLICITARO SIN VOZ",
    "PUBLICIDAD -- MENCIONES",
    "PUBLICIDAD -- SPOT PUBLICITARIO MENSUAL 15 PASADAS (D-T-N)",
    "PUBLICIDAD -- SPOT PUBLICITARIO MENSUAL 6 PASADAS (D-T-N)",
    "PUBLICIDAD -- SPOT PUBLICITARIO MENSUAL 9 PASADAS (D-T-N)",
    "RECONEXIÓN",
    "RECONEXIÓN DUO",
    "RECONEXIÓN INTERNET",
    "RSJ INTERNET 100MG",
    "SALDO A FAVOR",
    "SERV. CODIFICADO",
    "SERVICIO DE TELÉFONO",
    "SERVICIO HD",
    "SPOT PUBLICITARIO",
    "TELÉFONO TUNANMARCA",
    "TRANSPORTE DE DATOS 10 MB",
    "TRANSPORTE DE DATOS 50 MB",
    "TRANSPORTE L2L BBVA",
    "TRANSPORTE L2L IMPORTADORA TECNICA",
    "TRANSPORTE L2L VOLVO",
    "TRASLADO",
    "TV CABLE E INTERNET",
    "TV CABLE FTTH",
]


# Se prueban en orden y gana el primero que case: «INSTALACIÓN DE ANEXOS» es
# una instalación y no un anexo, y por eso el prefijo de instalación va antes.
FAMILIAS_POR_PREFIJO = [
    ("INSTALACION", "INSTALLATION"),
    ("INSTALACIÓN", "INSTALLATION"),
    ("RECONEXIÓN", "REACTIVATION"),
    ("ANEXO", "ANNEX"),
    # Todo lo que se cobra mes a mes. El prorrateo en días y la exigencia de
    # periodo cuelgan de esta familia, así que aquí solo entra lo recurrente.
    ("MENSUALIDAD", "MONTHLY"),
    ("ALQUILER FIBRA", "MONTHLY"),
    ("ARRENDAMIENTO", "MONTHLY"),
    ("APP ", "MONTHLY"),
    ("DUO ", "MONTHLY"),
    ("ENLACE ", "MONTHLY"),
    ("INTERNET", "MONTHLY"),
    ("IP PÚBLICA", "MONTHLY"),
    ("IPTV", "MONTHLY"),
    ("PLAN ", "MONTHLY"),
    ("PROMO2 ", "MONTHLY"),
    ("RSJ ", "MONTHLY"),
    ("SERV. CODIFICADO", "MONTHLY"),
    ("SERVICIO DE TELÉFONO", "MONTHLY"),
    ("SERVICIO HD", "MONTHLY"),
    ("TELÉFONO ", "MONTHLY"),
    ("TRANSPORTE ", "MONTHLY"),
    ("TV CABLE", "MONTHLY"),
]


def familia_de(nombre):
    for prefijo, familia in FAMILIAS_POR_PREFIJO:
        if nombre.startswith(prefijo):
            return familia

    return "OTHER"


def codigo_de(nombre):
    """Un identificador estable y legible a partir del nombre.

    `slugify` deja fuera los signos que no sobreviven a una URL -el «&» de
    «1.1GB M&A», los paréntesis de las pasadas de publicidad-, así que dos
    nombres podrían chocar en el mismo código. El desempate va numerado.
    """
    return slugify(nombre)[:76] or "concepto"


def sembrar(apps, schema_editor):
    ChargeConcept = apps.get_model("payments", "ChargeConcept")

    existentes = set(
        ChargeConcept.objects.values_list("name", flat=True)
    )
    codigos = set(ChargeConcept.objects.values_list("code", flat=True))

    nuevos = []

    for nombre in CONCEPTOS:
        if nombre in existentes:
            continue

        code = codigo_de(nombre)

        if code in codigos:
            base, sufijo = code, 2
            while code in codigos:
                code = "%s-%s" % (base, sufijo)
                sufijo += 1

        codigos.add(code)
        nuevos.append(
            ChargeConcept(
                code=code,
                name=nombre,
                family=familia_de(nombre),
                is_active=True,
            )
        )

    ChargeConcept.objects.bulk_create(nuevos)


def limpiar(apps, schema_editor):
    """Retira solo lo que sembró esta migración y que nadie haya usado.

    Un concepto con deudas colgando no se puede borrar -la clave es PROTECT- y
    tampoco debería: la deuda dejaría de decir qué se cobró.
    """
    ChargeConcept = apps.get_model("payments", "ChargeConcept")

    ChargeConcept.objects.filter(
        name__in=CONCEPTOS, charges__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0005_chargeconcept_charge_concept_item"),
    ]

    operations = [
        migrations.RunPython(sembrar, limpiar),
    ]
