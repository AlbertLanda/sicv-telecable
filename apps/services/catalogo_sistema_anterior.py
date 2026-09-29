"""Planes del sistema anterior (SICAV) que el SICV debe poder ofrecer.

La migración manual registra a cada abonado con el plan que tiene contratado
en SICAV, así que la lista de planes tiene que traer también los que ya no se
venden: corporativos, PYME, convenios con entidades y las líneas 2020-2025.

Precio y política de cobro quedan sin fijar a propósito, igual que en
`0011_catalogo_contratos_de_servicio`: no hay tarifa confirmada y una cifra
inventada saldría en la cotización como oficial. Se configuran en
Configurar > Planes **antes** de registrar clientes con ellos, porque la
mensualidad se copia a la suscripción al crearla: un cliente dado de alta con
el plan en S/ 0 se queda sin mensualidad aunque el plan se corrija después.

Generación y categoría comercial también quedan vacías: son las que activan las
reglas de cobertura por sede (`commercial.coverage_rules_for`), y ninguna de
esas reglas se definió para estos planes.

Lo usan la migración `0017_planes_sistema_anterior`, para las bases que ya
existen, y `cargar_catalogo_comercial`, para las nuevas: en una base nueva
INTERNET, DUO y CABLE nacen en ese comando, después de las migraciones.
"""

import unicodedata


# Planes del SICV que ya eran el mismo plan del sistema anterior con otro
# nombre. Conservan código, precio y política; solo toman el nombre de SICAV
# para que la lista tenga una sola opción por plan.
RENOMBRES = [
    ("INT-2025-STD-300", "INTERNET 300MG - 2025"),
    ("INT-2025-STD-600", "INTERNET 600MG - 2025"),
    ("INT-2025-STD-800", "INTERNET 800MG - 2025"),
    ("INT-2025-STD-1000", "INTERNET 1000MG - 2025"),
    ("DUO-2025-STD-300", "DUO RESIDENCIAL 300MG - 2025"),
    ("DUO-2025-STD-600", "DUO RESIDENCIAL 600MG - 2025"),
    ("DUO-2025-STD-800", "DUO RESIDENCIAL 800MG - 2025"),
    ("DUO-2025-STD-1000", "DUO RESIDENCIAL 1000MG - 2025"),
    ("INT-2026-ECO-200", "INTERNET ECONÓMICO 200MG"),
    ("DUO-2026-ECO-200", "DUO ECONÓMICO 200MG"),
    # Se sembró como «RPR»; el nombre correcto en SICAV es «PR».
    ("APP-PREMIUM-PLUS-RPR", "APP PREMIUM PLUS - PR"),
]


# codigo, nombre tal como lo muestra SICAV, servicio, velocidad Mbps.
#
# Los «INTERNET DUO ...» e «INTERNET RESIDENCIAL DUO ...» son DUO: incluyen TV.
# La velocidad sale del nombre y se imprime en el contrato; sin velocidad en
# el nombre queda vacía.
PLANES = [
    ("SICAV-001", "DUO ECONÓMICO - 80", "DUO", None),
    ("SICAV-002", "DUO RESIDENCIAL 100MBPS - 100", "DUO", 100),
    ("SICAV-003", "DUO RESIDENCIAL 100MG - 2024", "DUO", 100),
    ("SICAV-004", "DUO RESIDENCIAL 1200MG - 2025", "DUO", 1200),
    ("SICAV-005", "DUO RESIDENCIAL 150MBPS - 115", "DUO", 150),
    ("SICAV-006", "DUO RESIDENCIAL 200MG - 2024", "DUO", 200),
    ("SICAV-007", "DUO RESIDENCIAL 300MG - 2024", "DUO", 300),
    ("SICAV-008", "DUO RESIDENCIAL 400MG - 2024", "DUO", 400),
    ("SICAV-009", "DUO RESIDENCIAL 600MG - 2024", "DUO", 600),
    ("SICAV-010", "DUO RESIDENCIAL 70MBPS - 90", "DUO", 70),
    ("SICAV-011", "INTERNET 100MG - 2024", "INTERNET", 100),
    ("SICAV-012", "INTERNET 1200MG - 2025", "INTERNET", 1200),
    ("SICAV-013", "INTERNET 200MG - 2024", "INTERNET", 200),
    ("SICAV-014", "INTERNET 200MG UGEL - FTTH", "INTERNET", 200),
    ("SICAV-015", "INTERNET 20MG - 2020 OFICIAL", "INTERNET", 20),
    ("SICAV-016", "INTERNET 20MG - 2022 OFICIAL", "INTERNET", 20),
    ("SICAV-017", "INTERNET 20MG - CENTRO DE SALUD DE APATA", "INTERNET", 20),
    ("SICAV-018", "INTERNET 20MG - HOSPITAL DOMINGO OLAVEGOYA - SALUD MENTAL", "INTERNET", 20),
    ("SICAV-019", "INTERNET 250MG - UGEL JAUJA", "INTERNET", 250),
    ("SICAV-020", "INTERNET 300MG - 2024", "INTERNET", 300),
    ("SICAV-021", "INTERNET 300MG - 2025 100", "INTERNET", 300),
    ("SICAV-022", "INTERNET 400MG - 2024", "INTERNET", 400),
    ("SICAV-023", "INTERNET 40MG - 2023 OFICIAL", "INTERNET", 40),
    ("SICAV-024", "INTERNET 40MG - RED DE SALUD HOGAR PROTEGIDO", "INTERNET", 40),
    ("SICAV-025", "INTERNET 600MG - 2024", "INTERNET", 600),
    ("SICAV-026", "INTERNET CORPORATIVO 1.1GB M&A", "INTERNET", 1100),
    ("SICAV-027", "INTERNET CORPORATIVO 1.25 GB GIGARED TAMBO", "INTERNET", 1250),
    ("SICAV-028", "INTERNET CORPORATIVO 100 MG - MARCO", "INTERNET", 100),
    ("SICAV-029", "INTERNET CORPORATIVO 1200MG - BEGAKOM", "INTERNET", 1200),
    ("SICAV-030", "INTERNET CORPORATIVO 15 MB NAJAH", "INTERNET", 15),
    ("SICAV-031", "INTERNET CORPORATIVO 150MG MUNICIPALIDAD DE JAUJA", "INTERNET", 150),
    ("SICAV-032", "INTERNET CORPORATIVO 2000MG - CABLE MAS J&L", "INTERNET", 2000),
    ("SICAV-033", "INTERNET CORPORATIVO 200MG - 118", "INTERNET", 200),
    ("SICAV-034", "INTERNET CORPORATIVO 800MG GIGARED", "INTERNET", 800),
    ("SICAV-035", "INTERNET CORPORATIVO CORPORACIÓN GIGA 300 MG", "INTERNET", 300),
    ("SICAV-036", "INTERNET CORPORATIVO HOTEL TUNANMARCA", "INTERNET", None),
    ("SICAV-037", "INTERNET CORPORATIVO 1GB TELSA", "INTERNET", 1000),
    ("SICAV-038", "INTERNET DUO 60MG - 2023 PROMO OFICIAL", "DUO", 60),
    ("SICAV-039", "INTERNET DUO ECONÓMICO MARG. DERECHA", "DUO", None),
    ("SICAV-040", "INTERNET ECONÓMICO MARG. DERECHA 50MG", "INTERNET", 50),
    ("SICAV-041", "INTERNET PYME 1000MG - 2025", "INTERNET", 1000),
    ("SICAV-042", "INTERNET PYME 100MG - 2023", "INTERNET", 100),
    ("SICAV-043", "INTERNET PYME 150MG - 115", "INTERNET", 150),
    ("SICAV-044", "INTERNET PYME 160MG - 2020", "INTERNET", 160),
    ("SICAV-045", "INTERNET PYME 200MG - 2020", "INTERNET", 200),
    ("SICAV-046", "INTERNET PYME 200MG - 2023", "INTERNET", 200),
    ("SICAV-047", "INTERNET PYME 300MG - 2023", "INTERNET", 300),
    ("SICAV-048", "INTERNET PYME 400MG - 2023", "INTERNET", 400),
    ("SICAV-049", "INTERNET PYME 40MG - RED DE SALUD DE JAUJA - YAUYOS", "INTERNET", 40),
    ("SICAV-050", "INTERNET PYME 80MG - HOSPITAL DOMINGO OLAVEGOYA USPP", "INTERNET", 80),
    ("SICAV-051", "INTERNET RDSVM 20MG", "INTERNET", 20),
    ("SICAV-052", "INTERNET RESIDENCIAL 100MG - 2023", "INTERNET", 100),
    ("SICAV-053", "INTERNET RESIDENCIAL 150MG - 2023", "INTERNET", 150),
    ("SICAV-054", "INTERNET RESIDENCIAL 200MG - 2023", "INTERNET", 200),
    ("SICAV-055", "INTERNET RESIDENCIAL 200MG - S/200.00", "INTERNET", 200),
    ("SICAV-056", "INTERNET RESIDENCIAL 300MG - 2023", "INTERNET", 300),
    ("SICAV-057", "INTERNET RESIDENCIAL 70MG - 2023", "INTERNET", 70),
    ("SICAV-058", "INTERNET RESIDENCIAL DUO 100MG - 2023", "DUO", 100),
    ("SICAV-059", "INTERNET RESIDENCIAL DUO 150MG - 2023", "DUO", 150),
    ("SICAV-060", "INTERNET RESIDENCIAL DUO 200MG - 2023", "DUO", 200),
    ("SICAV-061", "INTERNET RESIDENCIAL DUO 300MG - 2023", "DUO", 300),
    ("SICAV-062", "INTERNET RESIDENCIAL DUO 70MG - 2023", "DUO", 70),
    ("SICAV-063", "INTERNET RESIDENCIAL MUNICIPALIDADES 600 MG", "INTERNET", 600),
    ("SICAV-064", "INTERNET UGEL JAUJA 600MG", "INTERNET", 600),
    ("SICAV-065", "PLAN ESPECIAL COLABORADOR TELECABLE - DUO", "DUO", None),
    ("SICAV-066", "PLAN ESPECIAL COLABORADORES TELECABLE - DUO", "DUO", None),
    ("SICAV-067", "PLAN ESPECIAL HOTEL MUQUIYAUYO CORPORACIÓN JEMAQUITA SAC", "INTERNET", None),
    ("SICAV-068", "PROMO2 DUO RESIDENCIAL 1000MG - 2024", "DUO", 1000),
    ("SICAV-069", "PROMO2 DUO RESIDENCIAL 200MG - 2024", "DUO", 200),
    ("SICAV-070", "PROMO2 DUO RESIDENCIAL 400MG - 2024", "DUO", 400),
    ("SICAV-071", "PROMO2 DUO RESIDENCIAL 600MG - 2024", "DUO", 600),
    ("SICAV-072", "PROMO2 DUO RESIDENCIAL 800MG - 2024", "DUO", 800),
    ("SICAV-073", "PROMO2 INTERNET 1000MG - 2024", "INTERNET", 1000),
    ("SICAV-074", "PROMO2 INTERNET 100MG - 2024", "INTERNET", 100),
    ("SICAV-075", "PROMO2 INTERNET 200MG - 2024", "INTERNET", 200),
    ("SICAV-076", "PROMO2 INTERNET 400MG - 2024", "INTERNET", 400),
    ("SICAV-077", "PROMO2 INTERNET 600MG - 2024", "INTERNET", 600),
    ("SICAV-078", "PROMO2 INTERNET 800MG - 2024", "INTERNET", 800),
    ("SICAV-079", "RSJ INTERNET 100MG", "INTERNET", 100),
    # Distinto de «TV CABLE FTTH - 40». Como los otros dos planes FTTH,
    # incluye dos puntos de TV en el alta (ver 0013_tv_cable_ftth_dos_puntos).
    ("SICAV-080", "TV CABLE FTTH - 45", "CABLE", None),
]


def _comparable(name):
    return " ".join(
        unicodedata.normalize("NFKD", name or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .upper()
        .split()
    )


def sembrar_planes_sistema_anterior(Plan, ServiceType):
    """Renombra y crea los planes de SICAV sin tocar lo ya configurado.

    Recibe los modelos para servir igual a una migración -modelos
    históricos- que a un comando. Solo crea: un plan existente conserva el
    precio y la política que se le hayan puesto en Configurar > Planes, y uno
    con el mismo nombre bajo otro código no se duplica. Un plan cuyo servicio
    todavía no existe se omite; lo crea después `cargar_catalogo_comercial`.
    """
    stats = {"renamed": 0, "created": 0, "skipped": 0}

    for code, name in RENOMBRES:
        stats["renamed"] += (
            Plan.objects.filter(code=code).exclude(name=name).update(name=name)
        )

    services = {service.code: service for service in ServiceType.objects.all()}
    names = {_comparable(name) for name in Plan.objects.values_list("name", flat=True)}

    for code, name, service_code, speed in PLANES:
        service = services.get(service_code)

        if (
            service is None
            or _comparable(name) in names
            or Plan.objects.filter(code=code).exists()
        ):
            stats["skipped"] += 1
            continue

        Plan.objects.create(
            code=code,
            name=name,
            service_type=service,
            generation=None,
            commercial_category="",
            billing_policy=None,
            speed_mbps=speed,
            technology="FTTH" if service_code == "CABLE" else "",
            monthly_price=0,
            included_tv_points=2 if service_code == "CABLE" else 0,
            requires_geographic_tariff=False,
            is_active=True,
        )
        names.add(_comparable(name))
        stats["created"] += 1

    return stats
