"""
Componentes de presentación del abonado.

El resumen del cliente aparece en la ficha y en el alta de órdenes. Se
resuelve aquí, en un solo sitio, para que las dos pantallas no describan
al mismo cliente con criterios distintos —qué dirección es la principal,
qué cuenta como servicio activo, qué OT sigue abierta—.
"""

from django import template

from apps.services.models import Subscription
from apps.work_orders.models import WorkOrder

register = template.Library()


@register.inclusion_tag("customers/_hero.html")
def customer_hero(customer, heading_level=2):
    """
    Resumen del abonado: identidad, contacto, ubicación y cifras vivas.

    `heading_level` existe porque el bloque no siempre es el título de la
    pantalla: en la ficha del cliente sí, pero en el alta de una orden el
    encabezado es «Nueva orden de trabajo» y duplicar el `h1` dejaría la
    página con dos títulos.
    """

    addresses = list(customer.addresses.all())

    primary_address = next(
        (address for address in addresses if address.is_primary),
        addresses[0] if addresses else None,
    )

    return {
        "customer": customer,
        "primary_address": primary_address,
        "heading_level": heading_level,
        "active_subscription_count": (
            Subscription.objects
            .filter(
                customer=customer,
                status=Subscription.Status.ACTIVE,
            )
            .count()
        ),
        "open_order_count": (
            WorkOrder.objects
            .filter(
                subscription__customer=customer,
                status__in=WorkOrder.ACTIVE_STATUSES,
            )
            .count()
        ),
    }
