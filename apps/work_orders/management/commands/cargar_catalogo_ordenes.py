"""
Carga el catálogo de servicios y motivos de orden del SICV.

El SICV operativo ofrece al ATC tres selectores encadenados:

    Suscripción  ->  el servicio contratado (INTERNET / CABLE / DUO)
    Servicio     ->  qué se va a emitir sobre esa suscripción
    Motivo       ->  por qué se emite

Este comando siembra el segundo y el tercero. El primero vive en el
catálogo comercial (`cargar_catalogo_comercial`).

Los nombres se guardan en mayúsculas porque así los lee el operador en el
SICV que se está reemplazando: cambiar la grafía obligaría a reaprender un
listado que ya se usa a diario.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError

from apps.services.models import ServiceType
from apps.work_orders.models import OrderReason, OrderType

TECHNICAL = OrderReason.Classification.TECHNICAL
ADMINISTRATIVE = OrderReason.Classification.ADMINISTRATIVE

INTERNET = "INTERNET"
CABLE = "CABLE"
DUO = "DUO"

# Servicios que llevan señal de internet y servicios que llevan señal de
# cable. DUO es ambos, así que hereda los dos bloques.
WITH_INTERNET = (INTERNET, DUO)
WITH_CABLE = (CABLE, DUO)
EVERY_SERVICE = (INTERNET, CABLE, DUO)

# (código, nombre, descripción, servicios, [(código motivo, nombre, clasificación)])
ORDER_CATALOG = [
    # -----------------------------------------------------------------
    # TRANSVERSALES
    #
    # Existen para cualquier suscripción: no dependen de si el abonado
    # tiene internet, cable o ambos.
    # -----------------------------------------------------------------
    (
        "INSTALLATION",
        "INSTALACIÓN",
        "Instalación inicial de un servicio contratado.",
        EVERY_SERVICE,
        [
            ("REQUIRED", "REQUERIDO", TECHNICAL),
            # Lo emite el alta comercial automática, no el ATC a mano.
            ("NEW_CLIENT", "CLIENTE NUEVO", TECHNICAL),
        ],
    ),
    (
        "CHANGE_PLAN",
        "CAMBIO DE PLAN",
        "Migración del abonado a otro plan comercial.",
        EVERY_SERVICE,
        [
            ("REQUIRED", "REQUERIDO", ADMINISTRATIVE),
        ],
    ),
    (
        "CUT",
        "CORTE",
        "Suspensión del servicio, voluntaria o por morosidad.",
        EVERY_SERVICE,
        [
            ("VOLUNTARY", "CORTE VOLUNTARIO", ADMINISTRATIVE),
            ("DELINQUENCY", "CORTE MOROSIDAD", ADMINISTRATIVE),
            ("DEF_BETTER_OFFER", "DEFINITIVO - MEJOR OFERTA", ADMINISTRATIVE),
            ("DEF_BAD_EXPERIENCE", "DEFINITIVO - MALA EXPERIENCIA", ADMINISTRATIVE),
            ("DEF_MOVING", "DEFINITIVO - CAMBIO DE RESIDENCIA", ADMINISTRATIVE),
        ],
    ),
    (
        "RECONNECTION",
        "RECONEXIÓN",
        "Restitución del servicio tras un corte.",
        EVERY_SERVICE,
        [
            ("RECONNECTION", "RECONEXIÓN", TECHNICAL),
        ],
    ),
    (
        "REQUIREMENT",
        "REQUERIMIENTO",
        "Solicitud del abonado que no es avería ni alta ni baja.",
        EVERY_SERVICE,
        [
            ("WIFI_PASSWORD", "CLAVE DE WIFI", TECHNICAL),
            ("TECH_CHANGE", "CAMBIO DE TECNOLOGÍA", TECHNICAL),
            ("DROP_REVIEW", "REVISIÓN DROP", TECHNICAL),
            ("TRANSFER", "TRASLADO", TECHNICAL),
            ("OUTSIDE_PLANT", "TRABAJOS PLANTA EXTERNA", TECHNICAL),
            ("FTTH_MIGRATION", "MIGRACIÓN A FTTH", TECHNICAL),
            ("EQUIPMENT_CHANGE", "CAMBIO DE EQUIPO", TECHNICAL),
            ("REPEATER", "INSTALACIÓN DE REPETIDOR", TECHNICAL),
            ("NOC_VISIT", "VISITA NOC", TECHNICAL),
        ],
    ),
    (
        "WITHDRAWAL",
        "RETIRO",
        "Retiro físico de los equipos del abonado.",
        EVERY_SERVICE,
        [
            ("REQUIRED", "REQUERIDO", TECHNICAL),
        ],
    ),
    (
        "LOGICAL_WITHDRAWAL",
        "RETIRO LÓGICO",
        "Baja en sistema sin visita técnica.",
        EVERY_SERVICE,
        [
            ("DEFINITIVE_CUT", "CORTE DEFINITIVO", ADMINISTRATIVE),
        ],
    ),
    # -----------------------------------------------------------------
    # SEÑAL DE INTERNET
    # -----------------------------------------------------------------
    (
        "INTERNET_FAULT",
        "AVERÍA INTERNET",
        "Falla del servicio de internet reportada por el abonado.",
        WITH_INTERNET,
        [
            ("UNCONFIGURED_CPE", "EQUIPO DESCONFIGURADO", TECHNICAL),
            ("FAULTY_CPE", "EQUIPO AVERIADO", TECHNICAL),
            ("NO_REMOTE_ACCESS", "SIN ACCESO REMOTO", TECHNICAL),
            ("HIGH_POWER", "POTENCIA ELEVADA", TECHNICAL),
            ("ONT_OFFLINE", "ONT SIN CONEXIÓN", TECHNICAL),
            ("DROP_DAMAGED_IN", "DROP DAÑADO INTERNO", TECHNICAL),
            ("DROP_DAMAGED_OUT", "DROP DAÑADO EXTERNO", TECHNICAL),
            ("CONNECTOR_DAMAGED_IN", "CONECTOR DAÑADO INTERNO", TECHNICAL),
            ("CONNECTOR_DAMAGED_OUT", "CONECTOR DAÑADO EXTERNO", TECHNICAL),
        ],
    ),
    (
        "NOC_INCIDENT",
        "INCIDENCIA NOC",
        "Degradación detectada o atendida por el NOC.",
        WITH_INTERNET,
        [
            ("NO_SIGNAL", "SIN SEÑAL", TECHNICAL),
            ("SLOW_SIGNAL", "SEÑAL LENTA", TECHNICAL),
            ("SOME_PAGES_FAIL", "FALLAN ALGUNAS PÁGINAS", TECHNICAL),
        ],
    ),
    # -----------------------------------------------------------------
    # SEÑAL DE CABLE
    # -----------------------------------------------------------------
    (
        "CABLE_FAULT",
        "AVERÍA CABLE",
        "Falla de la señal de televisión reportada por el abonado.",
        WITH_CABLE,
        [
            ("NO_SIGNAL", "SIN SEÑAL", TECHNICAL),
            ("BLURRY_SIGNAL", "SEÑAL BORROSA", TECHNICAL),
            ("EQUIPMENT_CHANGE", "CAMBIO DE EQUIPO", TECHNICAL),
        ],
    ),
    (
        "CABLE_SERVICES",
        "SERVICIOS",
        "Trabajos sobre la instalación de cable del abonado.",
        WITH_CABLE,
        [
            ("ANNEX_CUT", "CORTE DE ANEXO", TECHNICAL),
            ("ANNEX_INSTALL", "INSTALACIÓN DE ANEXO", TECHNICAL),
            ("COURTESY_TV", "INSTALACIÓN DE TV DE CORTESÍA", TECHNICAL),
            ("WIRING_CHANGE", "MODIFICACIÓN DE CABLEADO", TECHNICAL),
            ("CHANNEL_REPROGRAM", "REPROGRAMACIÓN DE CANALES", TECHNICAL),
            ("CHANNEL_RESYNC", "RESINCRONIZACIÓN DE CANALES (NOC)", TECHNICAL),
        ],
    ),
]

# Tipos de orden que ya existían antes de este catálogo y que no forman
# parte del listado operativo, pero cuyo ámbito sí conviene declarar para
# que no se ofrezcan sobre servicios que no los admiten.
LEGACY_SCOPES = {
    "TV_ANNEX": ("ANEXOS DE TV", WITH_CABLE),
}

# Tipos que este comando llegó a sembrar y que ya no forman parte del
# catálogo operativo. Se retiran aquí en vez de solo borrarlos de la
# tabla: sin esto seguirían ofreciéndose en cualquier entorno donde el
# comando ya se hubiera ejecutado.
RETIRED_ORDER_TYPES = [
    "TAC_INCIDENT",
]


class Command(BaseCommand):
    help = (
        "Carga/actualiza el catálogo de servicios y motivos de orden del SICV "
        "sin duplicar registros ni desactivar lo que ya estuviera en uso."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Ejecuta todas las validaciones y muestra el resumen, "
                "pero revierte los cambios."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        self.stdout.write(
            self.style.MIGRATE_HEADING("Catálogo de órdenes SICV")
        )

        services = self._load_service_types()
        stats = self._load_order_catalog(services)
        self._apply_legacy_scopes(services)
        self._retire_order_types()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Resumen"))
        self.stdout.write(
            f"  Servicios: {stats['types_created']} creados / "
            f"{stats['types_updated']} actualizados"
        )
        self.stdout.write(
            f"  Motivos: {stats['reasons_created']} creados / "
            f"{stats['reasons_updated']} actualizados"
        )

        if dry_run:
            transaction.set_rollback(True)
            self.stdout.write(
                self.style.WARNING("DRY RUN: no se guardó ningún cambio.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("Catálogo de órdenes cargado correctamente.")
            )

    def _load_service_types(self):
        """
        Los tipos de servicio son requisito, no algo que este comando cree.

        Inventarlos aquí duplicaría la fuente de verdad del catálogo
        comercial y dejaría dos definiciones de INTERNET/CABLE/DUO que
        podrían divergir.
        """

        services = {
            service.code: service
            for service in ServiceType.objects.filter(
                code__in=EVERY_SERVICE
            )
        }

        missing = sorted(set(EVERY_SERVICE) - set(services))

        if missing:
            raise CommandError(
                "Faltan tipos de servicio: "
                f"{', '.join(missing)}. "
                "Ejecute primero `cargar_catalogo_comercial`."
            )

        return services

    def _load_order_catalog(self, services):
        stats = {
            "types_created": 0,
            "types_updated": 0,
            "reasons_created": 0,
            "reasons_updated": 0,
        }

        for code, name, description, scope, reasons in ORDER_CATALOG:
            order_type, created = OrderType.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "description": description,
                    "is_active": True,
                },
            )

            order_type.service_types.set(
                [services[service_code] for service_code in scope]
            )

            order_type.full_clean()
            order_type.save()

            stats["types_created" if created else "types_updated"] += 1

            for reason_code, reason_name, classification in reasons:
                _, reason_created = OrderReason.objects.update_or_create(
                    order_type=order_type,
                    code=reason_code,
                    defaults={
                        "name": reason_name,
                        "classification": classification,
                        "is_active": True,
                    },
                )

                stats[
                    "reasons_created" if reason_created else "reasons_updated"
                ] += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"  OK {name}: {'/'.join(scope)} · {len(reasons)} motivos"
                )
            )

        return stats

    def _retire_order_types(self):
        """
        Saca del catálogo lo que dejó de ser operativo.

        Se intenta borrar, pero si alguna orden ya lo referencia el borrado
        está protegido y se desactiva en su lugar: dejar de ofrecer un tipo
        no puede costar el historial de las OT que se emitieron con él.
        """

        for code in RETIRED_ORDER_TYPES:
            order_type = OrderType.objects.filter(code=code).first()

            if order_type is None:
                continue

            reasons = OrderReason.objects.filter(order_type=order_type)

            try:
                with transaction.atomic():
                    reasons.delete()
                    order_type.delete()
            except ProtectedError:
                reasons.update(is_active=False)

                OrderType.objects.filter(pk=order_type.pk).update(
                    is_active=False
                )

                self.stdout.write(
                    self.style.WARNING(
                        f"  OK {order_type.name}: desactivado "
                        "(hay órdenes que lo referencian)"
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"  OK {order_type.name}: retirado")
                )

    def _apply_legacy_scopes(self, services):
        for code, (name, scope) in LEGACY_SCOPES.items():
            order_type = OrderType.objects.filter(code=code).first()

            if order_type is None:
                continue

            # El nombre se normaliza a mayúsculas para que el selector de
            # servicio no mezcle grafías con el catálogo operativo.
            order_type.name = name
            order_type.save(update_fields=["name"])

            order_type.service_types.set(
                [services[service_code] for service_code in scope]
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"  OK {order_type.name}: {'/'.join(scope)} (ámbito heredado)"
                )
            )
