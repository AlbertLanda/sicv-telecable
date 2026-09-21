"""Servicios y planes que el contrato de servicio necesita ofrecer.

El catalogo vivo solo tenia INTERNET, CABLE y DUO, que son los tres servicios
con precios confirmados y tarifa por sede. El contrato de servicio, en cambio,
se firma tambien sobre lo que la empresa vende fuera de la masiva: telefonia,
arrendamiento de fibra oscura, transporte de datos entre sedes y las
aplicaciones de streaming.

Se siembra por migracion y no solo desde `cargar_catalogo_comercial` porque
las bases que ya estan en uso -la de cada quien y la del equipo- no vuelven a
correr ese comando: si el catalogo llegara solo por ahi, el combo de servicio
del contrato aparecia con tres opciones en unas bases y con siete en otras.

Precios y politica de cobro quedan sin fijar a proposito: de estos servicios
no hay tarifa confirmada, y sembrar una cifra inventada la volveria oficial en
la cotizacion. Se configuran en Configurar > Planes cuando negocio las
confirme; hasta entonces el plan se muestra sin politica asignada, que es lo
que efectivamente se sabe de el.

CABLE es el mismo servicio de siempre, solo pasa a llamarse TV CABLE, como lo
nombra el formulario del sistema anterior. No se crea si no existe: en una
base nueva lo crea `cargar_catalogo_comercial`, que es donde viven sus tarifas
por sede, y alli tambien nacen sus dos planes FTTH.
"""

from django.db import migrations


SERVICIOS = [
    # codigo, nombre, descripcion, requiere cuenta PlayHub
    (
        "TELEFONO",
        "SERVICIO DE TELÉFONO",
        "Telefonía fija y enlaces de voz contratados por entidad.",
        False,
    ),
    (
        "FIBRA_OSCURA",
        "FIBRA OSCURA",
        "Arrendamiento de fibra óptica sin iluminar.",
        False,
    ),
    (
        "TRANSPORTE_DATOS",
        "TRANSPORTE DE DATOS",
        "Transporte de datos entre sedes del abonado.",
        False,
    ),
    (
        "APPS",
        "APPS",
        "Aplicaciones de streaming entregadas a una cuenta PlayHub.",
        True,
    ),
]


PLANES = [
    # codigo, nombre, servicio, velocidad Mbps
    ("TEL-RDSVM", "SERVICIO DE TELÉFONO - RDSVM", "TELEFONO", None),
    ("TEL-UGEL", "SERVICIO DE TELÉFONO - UGEL", "TELEFONO", None),
    ("TEL-TUNANMARCA", "TELÉFONO TUNANMARCA", "TELEFONO", None),
    ("FO-XIRRUS", "ARRENDAMIENTO FIBRA OSCURA XIRRUS TEC", "FIBRA_OSCURA", None),
    (
        "TD-ON-10MB",
        "TRANSPORTE DE DATOS 10 MB - OPTICAL NETWORKS",
        "TRANSPORTE_DATOS",
        10,
    ),
    ("APP-ESTANDAR", "APP ESTANDAR", "APPS", None),
    ("APP-PREMIUM", "APP PREMIUM", "APPS", None),
    ("APP-PREMIUM-ST", "APP PREMIUM - ST", "APPS", None),
    ("APP-PREMIUM-PLUS", "APP PREMIUM PLUS", "APPS", None),
    ("APP-PREMIUM-PLUS-RPR", "APP PREMIUM PLUS - RPR", "APPS", None),
    ("APP-PREMIUM-PLUS-ST", "APP PREMIUM PLUS - ST", "APPS", None),
    ("APP-TELECABLE", "APP TELECABLE", "APPS", None),
]


# Los dos planes del servicio de cable que el contrato ofrece hoy. Van aparte
# porque cuelgan de CABLE, que esta migracion no crea.
PLANES_TV_CABLE = [
    ("TVC-FTTH-40", "TV CABLE FTTH - 40"),
    ("TVC-FTTH-50", "TV CABLE FTTH - 50"),
]


def sembrar_catalogo(apps, schema_editor):
    ServiceType = apps.get_model("services", "ServiceType")
    Plan = apps.get_model("services", "Plan")

    servicios = {}

    for codigo, nombre, descripcion, requiere_playhub in SERVICIOS:
        servicio, _ = ServiceType.objects.get_or_create(
            code=codigo,
            defaults={
                "name": nombre,
                "description": descripcion,
                "supports_tv_annexes": False,
                "annex_installation_price": 0,
                "annex_monthly_price": 0,
                "requires_playhub_account": requiere_playhub,
                "is_active": True,
            },
        )
        servicios[codigo] = servicio

    for codigo, nombre, codigo_servicio, velocidad in PLANES:
        Plan.objects.get_or_create(
            code=codigo,
            defaults={
                "name": nombre,
                "service_type": servicios[codigo_servicio],
                "generation": None,
                "commercial_category": "",
                "billing_policy": None,
                "speed_mbps": velocidad,
                "technology": "",
                "monthly_price": 0,
                "included_tv_points": 0,
                "requires_geographic_tariff": False,
                "is_active": True,
            },
        )

    # Los tres servicios que ya existian se nombran como el resto: el combo
    # del contrato los lista juntos, y «Duo» entre «FIBRA OSCURA» y «TRANSPORTE
    # DE DATOS» se leia como si fuera de otro catalogo. El codigo no cambia:
    # lo referencian el catalogo de ordenes y las reglas de metraje.
    for codigo, nombre in (("INTERNET", "INTERNET"), ("DUO", "DUO")):
        ServiceType.objects.filter(code=codigo).exclude(name=nombre).update(
            name=nombre,
        )

    cable = ServiceType.objects.filter(code="CABLE").first()

    if cable is None:
        return

    if cable.name != "TV CABLE":
        cable.name = "TV CABLE"
        cable.save(update_fields=["name"])

    for codigo, nombre in PLANES_TV_CABLE:
        Plan.objects.get_or_create(
            code=codigo,
            defaults={
                "name": nombre,
                "service_type": cable,
                "generation": None,
                "commercial_category": "",
                "billing_policy": None,
                "speed_mbps": None,
                "technology": "FTTH",
                "monthly_price": 0,
                # La cortesia inicial de TV de estos planes no esta
                # confirmada. Cero es lo unico que se sabe: cada punto
                # adicional se cobra como anexo hasta que negocio diga
                # cuantos entran sin cargo.
                "included_tv_points": 0,
                "requires_geographic_tariff": False,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0010_servicetype_requires_playhub_account"),
    ]

    operations = [
        # Sin reverso. Un plan sembrado aqui puede tener ya contratos y
        # suscripciones colgando -PROTECT-, asi que borrarlo al desandar la
        # migracion fallaria o dejaria el contrato sin plan. Revertir el
        # esquema no tiene por que llevarse el catalogo con el.
        migrations.RunPython(sembrar_catalogo, migrations.RunPython.noop),
    ]
