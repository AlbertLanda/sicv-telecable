"""Ajustes de integración de la ficha única de Orden Técnica.

Se mantiene `views.WorkOrderDetailView` como implementación base y aquí solo se
precisa cuándo el técnico puede editar. Claim deja la OT en ASSIGNED; los datos
de campo empiezan después de `start`, cuando la orden está IN_PROGRESS.
"""

from apps.work_orders.models import WorkOrder
from apps.work_orders.views import WorkOrderDetailView


class IntegratedWorkOrderDetailView(WorkOrderDetailView):
    """ATC siempre lee; el técnico edita únicamente durante IN_PROGRESS."""

    def _resolve_access(self, request, order):
        super()._resolve_access(request, order)

        self.can_edit = (
            self.can_edit
            and order.status == WorkOrder.Status.IN_PROGRESS
        )
