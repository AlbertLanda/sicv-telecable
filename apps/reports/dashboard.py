"""
Las cifras del dashboard: cómo está hoy la sede, de un vistazo.

Cada cifra se cuenta igual que la pantalla a la que lleva, para que el número
del tablero y el de la lista no se contradigan: las órdenes como la agenda,
las incidencias como la cola NOC y las altas como el reporte de ventas. Donde
esa pantalla todavía no existe -caja del día, cartera vencida- se cuenta con
la regla del modelo.

Todo se cuenta en la sede activa de la barra superior, como la agenda y el
reporte de ventas. La excepción son las incidencias NOC: la cola las muestra
de todas las sedes, y el dashboard también.

Cada bloque se arma solo para quien puede abrir su módulo: el dashboard no
enseña cifras de una pantalla que al usuario no se le abre.
"""

from dataclasses import dataclass, field

from django.db.models import (
    Count,
    DecimalField,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.urls import reverse

from apps.payments.models import (
    ZERO,
    Charge,
    Payment,
    PaymentAllocation,
    PaymentCommitment,
)
from apps.services.models import Subscription
from apps.work_orders.models import FAULT_ORDER_TYPE_CODES, WorkOrder
from apps.work_orders.services import (
    INCIDENT_ORDER_TYPE_CODE,
    INSTALLATION_ORDER_TYPE_CODE,
    TRANSFER_ORDER_TYPE_CODE,
)

from .sales import in_branch


#: Lo que la cola NOC cuenta como abierto.
OPEN_INCIDENT_STATUSES = (
    WorkOrder.Status.PENDING,
    WorkOrder.Status.IN_PROGRESS,
    WorkOrder.Status.REPROGRAMMED,
)


@dataclass
class Figure:
    """Una cifra del dashboard, ya decidida para la plantilla."""

    label: str
    value: object
    money: bool = False
    detail: str = ""
    url: str = ""
    link_label: str = ""
    breakdown: list = field(default_factory=list)


@dataclass
class Section:
    key: str
    title: str
    icon: str
    figures: list


def _plural(count, singular, plural):
    return f"{count} {singular if count == 1 else plural}"


# ---------- Cobranza ----------

def collected(branch, start, end):
    """Lo que entró a caja entre dos días: cobros confirmados, no anulados.

    Cuenta la fecha en que entró el dinero (`paid_at`), no la de emisión: un
    comprobante emitido como pendiente se cobra el día que se confirma.
    """
    payments = Payment.objects.filter(
        status=Payment.Status.REGISTERED,
        paid_at__date__gte=start,
        paid_at__date__lte=end,
    )

    if branch is not None:
        payments = payments.filter(branch=branch)

    return payments.aggregate(
        total=Coalesce(Sum("amount"), Value(ZERO)),
        count=Count("pk"),
    )


def overdue_debt(branch, day):
    """La deuda vencida de la sede: el saldo de cada cargo vencido.

    El saldo se resta en la base -lo emitido menos lo pagado con cobros
    confirmados- con la misma regla que `Charge.balance_on`. Vencido ya no
    tiene pronto pago, así que lo emitido es lo que se debe.
    """
    paid = Subquery(
        PaymentAllocation.objects.filter(
            charge=OuterRef("pk"),
            payment__status=Payment.Status.REGISTERED,
        )
        .values("charge")
        .annotate(total=Sum("amount"))
        .values("total")[:1],
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    charges = Charge.objects.overdue(day)

    if branch is not None:
        charges = charges.filter(customer__branch=branch)

    return (
        charges.annotate(paid=Coalesce(paid, Value(ZERO)))
        .annotate(owed=F("amount") - F("paid"))
        .filter(owed__gt=0)
        .aggregate(
            total=Coalesce(Sum("owed"), Value(ZERO)),
            customers=Count("customer", distinct=True),
        )
    )


def active_commitments(branch, day):
    """Compromisos en pie. Los vencidos pueden seguir marcados como activos
    hasta que alguien abre la cuenta del abonado; se descartan como lo hace
    `Charge.active_commitment`."""
    commitments = PaymentCommitment.objects.filter(
        status=PaymentCommitment.Status.ACTIVE,
        committed_date__gte=day,
    )

    if branch is not None:
        commitments = commitments.filter(customer__branch=branch)

    return commitments.count()


def collection_section(user, branch, day):
    figures = []

    if user.has_perm("payments.view_payment"):
        today = collected(branch, day, day)
        month = collected(branch, day.replace(day=1), day)

        figures += [
            Figure(
                "Cobrado hoy",
                today["total"],
                money=True,
                detail=_plural(today["count"], "cobro", "cobros"),
            ),
            Figure(
                "Cobrado en el mes",
                month["total"],
                money=True,
                detail=_plural(month["count"], "cobro", "cobros"),
            ),
        ]

    if user.has_perm("payments.view_charge"):
        debt = overdue_debt(branch, day)
        commitments = active_commitments(branch, day)

        figures += [
            Figure(
                "Deuda vencida",
                debt["total"],
                money=True,
                detail=f"de {_plural(debt['customers'], 'abonado', 'abonados')}",
            ),
            Figure(
                "Compromisos de pago",
                commitments,
                detail="en pie hoy",
            ),
        ]

    return figures


# ---------- Operaciones ----------

def _scheduled_on(day):
    """Programadas ese día, como las cuenta la agenda."""
    return (
        Q(scheduled_at__isnull=False, scheduled_at__date=day)
        | Q(scheduled_at__isnull=True, scheduled_date=day)
    )


def open_orders(branch):
    """Las órdenes abiertas de la sede, como la agenda, sin las incidencias
    NOC: esas tienen su propia cifra y no se agendan."""
    orders = WorkOrder.objects.filter(
        status__in=WorkOrder.ACTIVE_STATUSES,
    ).exclude(order_type__code=INCIDENT_ORDER_TYPE_CODE)

    if branch is not None:
        orders = orders.filter(branch=branch)

    return orders


def orders_by_kind(orders):
    """Instalaciones, averías, traslados y el resto, en ese orden."""
    counts = orders.aggregate(
        installations=Count(
            "pk", filter=Q(order_type__code=INSTALLATION_ORDER_TYPE_CODE)
        ),
        faults=Count("pk", filter=Q(order_type__code__in=FAULT_ORDER_TYPE_CODES)),
        transfers=Count("pk", filter=Q(order_type__code=TRANSFER_ORDER_TYPE_CODE)),
        total=Count("pk"),
    )
    others = (
        counts["total"]
        - counts["installations"]
        - counts["faults"]
        - counts["transfers"]
    )

    kinds = [
        ("Instalación", counts["installations"]),
        ("Avería", counts["faults"]),
        ("Traslado", counts["transfers"]),
        ("Otras", others),
    ]

    return counts["total"], [(label, count) for label, count in kinds if count]


def operations_section(user, branch, day):
    figures = []

    if user.has_perm("work_orders.view_workorder"):
        orders = open_orders(branch)
        total, kinds = orders_by_kind(orders)
        agenda = reverse("work_orders:schedule_board")
        schedule = orders.aggregate(
            today=Count("pk", filter=_scheduled_on(day)),
            unscheduled=Count(
                "pk",
                filter=Q(scheduled_at__isnull=True, scheduled_date__isnull=True),
            ),
        )

        figures += [
            Figure(
                "Órdenes abiertas",
                total,
                breakdown=kinds,
                url=agenda,
                link_label="Ver agenda",
            ),
            Figure(
                "Programadas para hoy",
                schedule["today"],
                url=agenda,
                link_label="Ver agenda",
            ),
            Figure(
                "Sin programar",
                schedule["unscheduled"],
                detail="esperan fecha",
                url=agenda,
                link_label="Ver agenda",
            ),
        ]

    if user.has_perm("work_orders.view_incident"):
        incidents = WorkOrder.objects.filter(
            order_type__code=INCIDENT_ORDER_TYPE_CODE,
            status__in=OPEN_INCIDENT_STATUSES,
        ).aggregate(
            total=Count("pk"),
            pending=Count("pk", filter=Q(status=WorkOrder.Status.PENDING)),
        )

        figures.append(
            Figure(
                "Incidencias NOC abiertas",
                incidents["total"],
                detail=f"{incidents['pending']} sin tomar · todas las sedes",
                url=reverse("work_orders:incident_noc_queue"),
                link_label="Ver cola NOC",
            )
        )

    return figures


# ---------- Comercial ----------

def commercial_section(user, branch, day):
    if not user.has_perm("services.view_subscription"):
        return []

    subscriptions = in_branch(Subscription.objects.all(), branch)
    counts = subscriptions.aggregate(
        active=Count("pk", filter=Q(status=Subscription.Status.ACTIVE)),
        # Como el reporte de ventas: toda suscripción registrada en el mes,
        # sea cual sea su estado.
        month=Count(
            "pk",
            filter=Q(
                created_at__date__gte=day.replace(day=1),
                created_at__date__lte=day,
            ),
        ),
        to_install=Count(
            "pk",
            filter=Q(
                status__in=(
                    Subscription.Status.PRESALE,
                    Subscription.Status.INSTALLATION,
                )
            ),
        ),
        cut=Count(
            "pk",
            filter=Q(
                status__in=(
                    Subscription.Status.CUT,
                    Subscription.Status.SUSPENDED,
                )
            ),
        ),
    )

    return [
        Figure("Servicios activos", counts["active"]),
        Figure(
            "Altas del mes",
            counts["month"],
            detail="servicios registrados",
            url=reverse("reports:sales"),
            link_label="Ver ventas",
        ),
        Figure("Por instalar", counts["to_install"], detail="en preventa o instalación"),
        Figure("Cortados o suspendidos", counts["cut"]),
    ]


def build_dashboard(user, branch, day):
    """Los bloques que el usuario puede ver, cada uno con sus cifras."""
    sections = [
        Section("cobranza", "Cobranza", "bi-cash-coin", collection_section(user, branch, day)),
        Section("operaciones", "Operaciones", "bi-briefcase", operations_section(user, branch, day)),
        Section("comercial", "Comercial", "bi-graph-up-arrow", commercial_section(user, branch, day)),
    ]

    return [section for section in sections if section.figures]
