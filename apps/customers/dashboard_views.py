"""Vista ejecutiva de la ficha del cliente.

Se apoya en CustomerDetailView para conservar consultas, permisos y actividad
reciente ya probados. Este módulo solo prepara un contexto más operativo para
la nueva composición visual: resumen, OT abierta destacada y vistas previas.
"""

from apps.contracts.models import Contract
from apps.services.models import Subscription
from apps.work_orders.models import WorkOrder

from .views import CustomerDetailView


class CustomerDashboardDetailView(CustomerDetailView):
    template_name = "customers/detail_dashboard.html"

    def get_template_names(self):
        """Mantiene accesible la explicación del permiso histórico.

        `assign_workorder` todavía existe y se reutiliza temporalmente para
        programación, aunque la asignación manual web ya fue retirada. Para
        usuarios que aún lo poseen se añade solo una aclaración accesible; no
        se renderiza enlace, botón ni formulario de asignación.
        """
        if self.request.user.has_perm("work_orders.assign_workorder"):
            return ["customers/detail_dashboard_legacy_permission.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        addresses = list(context["addresses"])
        subscriptions = list(context["subscriptions"])
        contracts = list(context["contracts"])
        work_orders = list(context["work_orders"])

        open_orders = [
            order for order in work_orders
            if order.status in WorkOrder.ACTIVE_STATUSES
        ]

        primary_address = next(
            (address for address in addresses if address.is_primary),
            addresses[0] if addresses else None,
        )

        primary_subscription = next(
            (
                subscription
                for subscription in subscriptions
                if subscription.status == Subscription.Status.ACTIVE
            ),
            subscriptions[0] if subscriptions else None,
        )

        active_contract = next(
            (
                contract
                for contract in contracts
                if contract.status == Contract.Status.ACTIVE
            ),
            contracts[0] if contracts else None,
        )

        recent_activity = list(context["recent_activity"])

        context.update(
            {
                "addresses": addresses,
                "subscriptions": subscriptions,
                "contracts": contracts,
                "work_orders": work_orders,
                "open_orders": open_orders,
                "featured_open_order": open_orders[0] if open_orders else None,
                "primary_address": primary_address,
                "primary_subscription": primary_subscription,
                "active_contract": active_contract,
                "recent_work_orders": work_orders[:5],
                "recent_activity_preview": recent_activity[:5],
                "open_order_count": len(open_orders),
                "active_subscription_count": sum(
                    1
                    for subscription in subscriptions
                    if subscription.status == Subscription.Status.ACTIVE
                ),
            }
        )

        return context
