"""Las pestañas de la ficha del cliente.

Información, órdenes y actividad son tres pantallas del mismo abonado, cada
una con su URL. Antes eran una sola página que lo apilaba todo -resumen,
previsualizaciones, tablas completas- y repetía cada bloque dos veces: una
como vista previa y otra entera más abajo.

Las tres se apoyan en CustomerDetailView para conservar consultas, permisos y
actividad reciente ya probados; aquí solo se elige qué mira cada pestaña.
"""

from django.core.paginator import Paginator

from apps.contracts.models import Contract
from apps.services.models import Subscription
from apps.work_orders.models import WorkOrder

from .views import CustomerDetailView


#: Filas por página de las tablas del abonado. Una sola constante para que
#: cambiar de pestaña no cambie cuánto se ve de golpe.
ROWS_PER_PAGE = 15


class CustomerRecordTabView(CustomerDetailView):
    """Lo que comparten las pestañas: el abonado y su encabezado.

    El encabezado -identidad, servicio activo, OT abierta- se pinta igual en
    todas: si cada pestaña lo resolviera por su cuenta, dos podrían acabar
    diciendo cosas distintas del mismo cliente.
    """

    active_tab = "info"

    def paginate(self, rows):
        """Reparte una lista ya cargada en páginas de `ROWS_PER_PAGE`.

        Se pagina en memoria, no en la base: la vista padre ya trajo las
        colecciones completas del abonado para resolver el encabezado, y
        volver a consultarlas por página las leería dos veces.
        """
        paginator = Paginator(rows, ROWS_PER_PAGE)
        page_obj = paginator.get_page(self.request.GET.get("page"))

        return {
            "paginator": paginator,
            "page_obj": page_obj,
            "is_paginated": page_obj.has_other_pages(),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        subscriptions = list(context["subscriptions"])
        work_orders = list(context["work_orders"])

        open_orders = [
            order for order in work_orders
            if order.status in WorkOrder.ACTIVE_STATUSES
        ]

        context.update(
            {
                "active_tab": self.active_tab,
                "subscriptions": subscriptions,
                "work_orders": work_orders,
                "open_orders": open_orders,
                "open_order_count": len(open_orders),
                "active_subscription_count": sum(
                    1
                    for subscription in subscriptions
                    if subscription.status == Subscription.Status.ACTIVE
                ),
            }
        )

        return context


class CustomerDashboardDetailView(CustomerRecordTabView):
    """Información: quién es el abonado, dónde vive y qué tiene contratado.

    No lleva órdenes, deuda ni actividad. Cada una tiene su pestaña, y
    resumirlas aquí obligaba a mantener dos versiones del mismo bloque.
    """

    template_name = "customers/detail_dashboard.html"
    active_tab = "info"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        addresses = list(context["addresses"])
        contracts = list(context["contracts"])

        primary_address = next(
            (address for address in addresses if address.is_primary),
            addresses[0] if addresses else None,
        )

        primary_subscription = next(
            (
                subscription
                for subscription in context["subscriptions"]
                if subscription.status == Subscription.Status.ACTIVE
            ),
            context["subscriptions"][0] if context["subscriptions"] else None,
        )

        active_contract = next(
            (
                contract
                for contract in contracts
                if contract.status == Contract.Status.ACTIVE
            ),
            contracts[0] if contracts else None,
        )

        map_embed_url = ""
        if (
            primary_address
            and getattr(primary_address, "map_link", "")
            and primary_address.latitude is not None
            and primary_address.longitude is not None
        ):
            latitude = str(primary_address.latitude)
            longitude = str(primary_address.longitude)
            map_embed_url = (
                "https://maps.google.com/maps"
                f"?q={latitude},{longitude}&z=16&output=embed"
            )

        context.update(
            {
                "addresses": addresses,
                "contracts": contracts,
                "primary_address": primary_address,
                "primary_subscription": primary_subscription,
                "active_contract": active_contract,
                "map_embed_url": map_embed_url,
            }
        )

        return context


class CustomerOrdersTabView(CustomerRecordTabView):
    """Órdenes: la OT abierta que reclama atención y el resto en tabla."""

    template_name = "customers/detail_orders.html"
    active_tab = "orders"

    def get_template_names(self):
        """Mantiene accesible la explicación del permiso histórico.

        `assign_workorder` todavía existe y se reutiliza temporalmente para
        programación, aunque la asignación manual web ya fue retirada. Para
        usuarios que aún lo poseen se añade solo una aclaración accesible; no
        se renderiza enlace, botón ni formulario de asignación.

        La aclaración vive aquí y no en Información: es donde el que conserva
        el permiso viene a buscar el botón que ya no está.
        """
        if self.request.user.has_perm("work_orders.assign_workorder"):
            return ["customers/detail_orders_legacy_permission.html"]

        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        open_orders = context["open_orders"]
        context["featured_open_order"] = open_orders[0] if open_orders else None
        context.update(self.paginate(context["work_orders"]))

        return context


class CustomerActivityTabView(CustomerRecordTabView):
    """Actividad: lo que le fue pasando al abonado, de lo último a lo primero.

    Los eventos no salen de un modelo de historial: la vista padre los deriva
    de las fuentes reales -suscripciones, contratos, órdenes-, así que ya
    llegan como una lista en memoria.
    """

    template_name = "customers/detail_activity.html"
    active_tab = "activity"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        recent_activity = list(context["recent_activity"])
        context["recent_activity"] = recent_activity
        context.update(self.paginate(recent_activity))

        return context
