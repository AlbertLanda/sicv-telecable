from dataclasses import dataclass
from datetime import datetime

from apps.work_orders.models import (
    WorkOrder,
    WorkOrderAssignment,
    WorkOrderStatusHistory,
)

# Cantidad máxima de eventos que se muestran en el bloque de
# actividad reciente. Ver PDF de actividad, sección 4.2: "Primera
# versión recomendada: hasta 20 eventos recientes".
MAX_RECENT_EVENTS = 20

# Cantidad máxima de fuentes candidatas que se trae de cada origen
# antes de combinarlas y recortar al límite final. Se mantiene igual
# al límite final para no traer más filas de las necesarias.
CANDIDATES_PER_SOURCE = MAX_RECENT_EVENTS

# Badges Bootstrap por tipo de evento. El texto del título ya
# distingue el tipo de evento sin depender únicamente del color
# (ver sección 5 del PDF de actividad); el color es un refuerzo
# visual adicional.
EVENT_BADGE_CLASSES = {
    "SUBSCRIPTION": "bg-info text-dark",
    "CONTRACT": "bg-dark",
    "WORK_ORDER_CREATED": "bg-primary",
    "WORK_ORDER_STATUS": "bg-warning text-dark",
    "WORK_ORDER_ASSIGNMENT": "bg-success",
}


@dataclass
class CustomerActivityEvent:
    """Un evento normalizado para la línea de tiempo de actividad reciente."""

    timestamp: datetime
    event_type: str
    title: str
    reference: str
    detail: str = ""

    @property
    def badge_class(self):
        return EVENT_BADGE_CLASSES.get(self.event_type, "bg-secondary")


def build_customer_operational_summary(subscriptions, contracts, work_orders):
    subscriptions = list(subscriptions)
    contracts = list(contracts)
    work_orders = list(work_orders)

    open_work_orders = sum(
        1
        for order in work_orders
        if order.status in WorkOrder.ACTIVE_STATUSES
    )

    return {
        "total_subscriptions": len(subscriptions),
        "total_contracts": len(contracts),
        "total_work_orders": len(work_orders),
        "open_work_orders": open_work_orders,
    }


def _subscription_events(subscriptions):
    for subscription in subscriptions[:CANDIDATES_PER_SOURCE]:
        service_name = (
            subscription.service_type.name
            if subscription.service_type_id
            else ""
        )

        detail = " - ".join(
            part
            for part in (service_name, subscription.get_status_display())
            if part
        )

        yield CustomerActivityEvent(
            timestamp=subscription.created_at,
            event_type="SUBSCRIPTION",
            title="Servicio registrado",
            reference=f"Servicio #{subscription.service_number}",
            detail=detail,
        )


def _contract_events(contracts):
    for contract in contracts[:CANDIDATES_PER_SOURCE]:
        yield CustomerActivityEvent(
            timestamp=contract.created_at,
            event_type="CONTRACT",
            title="Contrato registrado",
            reference=contract.contract_number,
            detail=contract.get_status_display(),
        )


def _work_order_created_events(work_orders):
    for order in work_orders[:CANDIDATES_PER_SOURCE]:
        yield CustomerActivityEvent(
            timestamp=order.created_at,
            event_type="WORK_ORDER_CREATED",
            title="OT creada",
            reference=order.order_number,
            detail=order.order_type.name if order.order_type_id else "",
        )


def _work_order_status_events(customer):
    changes = (
        WorkOrderStatusHistory.objects
        .filter(work_order__subscription__customer=customer)
        .select_related("work_order")
        .order_by("-changed_at")[:CANDIDATES_PER_SOURCE]
    )

    for change in changes:
        previous = (
            change.get_previous_status_display()
            if change.previous_status
            else "Inicio"
        )

        yield CustomerActivityEvent(
            timestamp=change.changed_at,
            event_type="WORK_ORDER_STATUS",
            title="Estado cambiado",
            reference=change.work_order.order_number,
            detail=f"{previous} → {change.get_new_status_display()}",
        )


def _work_order_assignment_events(customer):
    assignments = (
        WorkOrderAssignment.objects
        .filter(work_order__subscription__customer=customer)
        .select_related("work_order", "technician")
        .order_by("-assigned_at")[:CANDIDATES_PER_SOURCE]
    )

    for assignment in assignments:
        yield CustomerActivityEvent(
            timestamp=assignment.assigned_at,
            event_type="WORK_ORDER_ASSIGNMENT",
            title="OT asignada",
            reference=assignment.work_order.order_number,
            detail=str(assignment.technician),
        )


def build_customer_recent_activity(
    customer,
    subscriptions,
    contracts,
    work_orders,
    limit=MAX_RECENT_EVENTS,
):
    """
    Construye la línea de tiempo de actividad reciente (sección 4.2
    del PDF de actividad) combinando eventos de las fuentes
    permitidas (sección 4.3).

    `subscriptions`, `contracts` y `work_orders` deben ser las
    colecciones ya cargadas por CustomerDetailView (evita repetir
    esas consultas). Los cambios de estado y las asignaciones sí
    requieren dos consultas adicionales propias, acotadas con
    select_related() y un límite explícito, para no traer todo el
    histórico del abonado.
    """

    subscriptions = list(subscriptions)
    contracts = list(contracts)
    work_orders = list(work_orders)

    events = []
    events.extend(_subscription_events(subscriptions))
    events.extend(_contract_events(contracts))
    events.extend(_work_order_created_events(work_orders))
    events.extend(_work_order_status_events(customer))
    events.extend(_work_order_assignment_events(customer))

    events.sort(key=lambda event: event.timestamp, reverse=True)

    return events[:limit]
