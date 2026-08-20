"""
Siembra el catálogo real de tipos de orden / subtipos / motivos para
SICV Telecable, separando lo que aplica a un plan solo CATV de lo que
aplica a un plan de Internet o Dúo.

Idempotente: usa get_or_create + actualización de campos, así que se
puede correr tantas veces como se quiera (por ejemplo en cada
despliegue) sin duplicar registros ni pisar el histórico de órdenes
ya creadas con estos catálogos.

Uso:
    python manage.py seed_work_order_catalog
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.work_orders.models import (
    OrderReason,
    OrderSubtype,
    OrderType,
    PlanScope,
)


# Motivos usados compartidos por TODAS las órdenes de servicio de CATV
# (aplican igual si el cliente es solo-CATV o Dúo).
CATV_SERVICE_REASONS = [
    ("NO_SIGNAL", "Sin señal"),
    ("BLURRY_SIGNAL", "Señal borrosa"),
    ("CHANNELS_FAIL", "Fallan algunos canales"),
    ("FAULTY_EQUIPMENT", "Equipo averiado"),
    ("HANGING_CABLE", "Cable colgado"),
    ("REQUESTED", "Solicitado"),
    ("ADDRESS_CHANGE", "Cambio de domicilio"),
    ("INTERNAL_TRANSFER", "Traslado interno"),
    ("DEFINITIVE", "Definitivo"),
    ("NON_PAYMENT", "Morosidad"),
    ("TEMPORARY", "Temporal"),
    ("VOLUNTARY", "Voluntario"),
]

# "Órdenes de servicio": mismos 9 tipos, visibles para CATV puro y Dúo
# (PlanScope.CATV ya cubre ambos casos, ver PlanScope.plan_scope_applies).
CATV_SERVICE_ORDER_TYPES = [
    ("SERVICE_TECH_CHANGE", "Cambio de tecnología"),
    ("SERVICE_ANNEX_CUT", "Corte de anexo"),
    ("SERVICE_ANNEX_INSTALL", "Instalación de anexo"),
    ("SERVICE_COURTESY_TV", "Instalación TV de cortesía"),
    ("SERVICE_WIRING_MOD", "Modificación de cableado"),
    ("SERVICE_CHANNEL_REPROGRAM", "Reprogramación de canales"),
    ("SERVICE_RESYNC_NOC", "Resincronización (NOC)"),
    ("SERVICE_SIGNAL_REVIEW", "Revisión de señal"),
    ("SERVICE_TRANSFER", "Traslado"),
]

NOC_INCIDENT_REASONS = [
    ("NOC_NO_SIGNAL", "Sin señal"),
    ("NOC_SLOW_SIGNAL", "Señal lenta"),
    ("NOC_UNSTABLE_SIGNAL", "Señal inestable"),
    ("NOC_PAGES_FAIL", "Fallan algunas páginas"),
]

REQUIREMENT_REASONS = [
    ("REQ_WIFI_PASSWORD", "Clave wifi"),
    ("REQ_TECH_CHANGE", "Cambio de tecnología"),
    ("REQ_DROP_REVIEW", "Revisión de drop"),
    ("REQ_TRANSFER", "Traslado"),
    ("REQ_EXTERNAL_PLANT", "Trabajos de planta externa"),
    ("REQ_FTTH_MIGRATION", "Migración FTTH"),
    ("REQ_EQUIPMENT_CHANGE", "Cambio de equipo"),
    ("REQ_REPEATER_INSTALL", "Instalación de repetidor"),
]

# Motivos del subtipo "Definitivo" de un corte de Internet/Dúo.
CUT_DEFINITIVE_REASONS = [
    ("CUT_DEF_BAD_EXPERIENCE", "Mala experiencia con el servicio"),
    ("CUT_DEF_RESIDENCE_CHANGE", "Cambio de residencia"),
    ("CUT_DEF_BETTER_OFFER", "Mejor oferta de la competencia"),
]


class Command(BaseCommand):
    help = (
        "Crea o actualiza el catálogo de tipos de orden, subtipos y "
        "motivos según el esquema operativo real (planes CATV vs "
        "Internet/Dúo)."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        self._seed_base_order_types()
        self._seed_catv_service_orders()
        self._seed_internet_orders()
        self._seed_internet_cut_breakdown()

        self.stdout.write(self.style.SUCCESS(
            "Catálogo de órdenes de trabajo actualizado correctamente."
        ))

    # ------------------------------------------------------------------
    # Tipos base, comunes a cualquier plan (CATV, Internet o Dúo):
    # Instalación, Reconexión y Corte. El corte se especializa más abajo
    # solo para Internet/Dúo (subtipos y motivos).
    # ------------------------------------------------------------------
    def _seed_base_order_types(self):
        base_types = [
            ("INSTALL", "Instalación", "Instalación de un nuevo servicio"),
            ("RECONNECT", "Reconexión", "Reconexión del servicio"),
            ("CUT", "Corte", "Corte del servicio"),
        ]

        for code, name, description in base_types:
            order_type, _ = OrderType.objects.get_or_create(
                code=code,
                defaults={"name": name, "description": description},
            )
            order_type.name = name
            order_type.plan_scope = PlanScope.ANY
            order_type.is_active = True
            order_type.save(update_fields=["name", "plan_scope", "is_active"])

    # ------------------------------------------------------------------
    # "Órdenes de servicio" de CATV: visibles para clientes solo-CATV y
    # también para Dúo (PlanScope.CATV = incluye TV por cable).
    # ------------------------------------------------------------------
    def _seed_catv_service_orders(self):
        for type_code, type_name in CATV_SERVICE_ORDER_TYPES:
            order_type, _ = OrderType.objects.get_or_create(
                code=type_code,
                defaults={"name": type_name},
            )
            order_type.name = type_name
            order_type.plan_scope = PlanScope.CATV
            order_type.is_active = True
            order_type.save(update_fields=["name", "plan_scope", "is_active"])

            for reason_code, reason_name in CATV_SERVICE_REASONS:
                reason, _ = OrderReason.objects.get_or_create(
                    order_type=order_type,
                    code=reason_code,
                    defaults={"name": reason_name},
                )
                reason.name = reason_name
                reason.plan_scope = PlanScope.CATV
                reason.is_active = True
                reason.save(update_fields=["name", "plan_scope", "is_active"])

    # ------------------------------------------------------------------
    # Tipos exclusivos de Internet/Dúo: Cambio de plan, Incidencia NOC
    # y Requerimiento.
    # ------------------------------------------------------------------
    def _seed_internet_orders(self):
        plan_change, _ = OrderType.objects.get_or_create(
            code="PLAN_CHANGE",
            defaults={"name": "Cambio de plan"},
        )
        plan_change.name = "Cambio de plan"
        plan_change.plan_scope = PlanScope.INTERNET
        plan_change.is_active = True
        plan_change.save(update_fields=["name", "plan_scope", "is_active"])

        self._seed_internet_order_with_reasons(
            code="NOC_INCIDENT",
            name="Incidencia NOC",
            reasons=NOC_INCIDENT_REASONS,
        )

        self._seed_internet_order_with_reasons(
            code="REQUIREMENT",
            name="Requerimiento",
            reasons=REQUIREMENT_REASONS,
        )

    def _seed_internet_order_with_reasons(self, code, name, reasons):
        order_type, _ = OrderType.objects.get_or_create(
            code=code,
            defaults={"name": name},
        )
        order_type.name = name
        order_type.plan_scope = PlanScope.INTERNET
        order_type.is_active = True
        order_type.save(update_fields=["name", "plan_scope", "is_active"])

        for reason_code, reason_name in reasons:
            reason, _ = OrderReason.objects.get_or_create(
                order_type=order_type,
                code=reason_code,
                defaults={"name": reason_name},
            )
            reason.name = reason_name
            reason.plan_scope = PlanScope.INTERNET
            reason.is_active = True
            reason.save(update_fields=["name", "plan_scope", "is_active"])

    # ------------------------------------------------------------------
    # Desglose del Corte para Internet/Dúo: Morosidad y Temporal no
    # llevan motivo adicional; Definitivo sí, con 3 motivos posibles.
    # ------------------------------------------------------------------
    def _seed_internet_cut_breakdown(self):
        cut_type = OrderType.objects.get(code="CUT")

        non_payment_subtype, _ = OrderSubtype.objects.get_or_create(
            order_type=cut_type,
            code="NON_PAYMENT",
            defaults={"name": "Morosidad"},
        )
        non_payment_subtype.name = "Morosidad"
        non_payment_subtype.plan_scope = PlanScope.INTERNET
        non_payment_subtype.is_active = True
        non_payment_subtype.save(
            update_fields=["name", "plan_scope", "is_active"]
        )

        temporary_subtype, _ = OrderSubtype.objects.get_or_create(
            order_type=cut_type,
            code="TEMPORARY",
            defaults={"name": "Temporal"},
        )
        temporary_subtype.name = "Temporal"
        temporary_subtype.plan_scope = PlanScope.INTERNET
        temporary_subtype.is_active = True
        temporary_subtype.save(
            update_fields=["name", "plan_scope", "is_active"]
        )

        definitive_subtype, _ = OrderSubtype.objects.get_or_create(
            order_type=cut_type,
            code="DEFINITIVE",
            defaults={"name": "Definitivo"},
        )
        definitive_subtype.name = "Definitivo"
        definitive_subtype.plan_scope = PlanScope.INTERNET
        definitive_subtype.is_active = True
        definitive_subtype.save(
            update_fields=["name", "plan_scope", "is_active"]
        )

        for reason_code, reason_name in CUT_DEFINITIVE_REASONS:
            reason, _ = OrderReason.objects.get_or_create(
                order_type=cut_type,
                code=reason_code,
                defaults={"name": reason_name, "subtype": definitive_subtype},
            )
            reason.name = reason_name
            reason.subtype = definitive_subtype
            reason.plan_scope = PlanScope.INTERNET
            reason.is_active = True
            reason.save(
                update_fields=["name", "subtype", "plan_scope", "is_active"]
            )
