"""
Filtros de presentación de las órdenes de trabajo.

Solo traducen un valor del dominio a una clase de Bootstrap. No deciden
nada: el texto visible siempre sale de get_status_display /
get_priority_display, de modo que la pantalla sigue siendo legible aunque
el color no se distinga o no se cargue la hoja de estilos.
"""

from django import template

from apps.work_orders.models import WorkOrder


register = template.Library()


STATUS_CSS = {
    WorkOrder.Status.PENDING: "bg-warning text-dark",
    WorkOrder.Status.ASSIGNED: "bg-primary",
    WorkOrder.Status.DERIVED: "bg-info text-dark",
    WorkOrder.Status.IN_PROGRESS: "bg-info text-dark",
    WorkOrder.Status.ATTENDED: "bg-success",
    WorkOrder.Status.LIQUIDATED: "bg-success",
    WorkOrder.Status.REPROGRAMMED: "bg-secondary",
    WorkOrder.Status.REJECTED: "bg-danger",
    WorkOrder.Status.NOT_FEASIBLE: "bg-danger",
    WorkOrder.Status.CANCELLED: "bg-dark",
}


PRIORITY_CSS = {
    WorkOrder.Priority.LOW: "text-bg-light border",
    WorkOrder.Priority.NORMAL: "text-bg-light border",
    WorkOrder.Priority.HIGH: "text-bg-warning",
    WorkOrder.Priority.URGENT: "text-bg-danger",
}


@register.filter
def status_css(status):
    """Clase del badge de estado. Un estado desconocido cae en neutro."""
    return STATUS_CSS.get(status, "bg-secondary")


@register.filter
def priority_css(priority):
    """Clase del badge de prioridad. Una prioridad desconocida cae en neutro."""
    return PRIORITY_CSS.get(priority, "text-bg-light border")
