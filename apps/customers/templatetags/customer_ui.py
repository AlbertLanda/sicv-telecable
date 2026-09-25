"""
Componentes de presentación del abonado.

El resumen del cliente aparece en la ficha y en el alta de órdenes. Se
resuelve aquí, en un solo sitio, para que las dos pantallas no describan
al mismo cliente con criterios distintos —qué dirección es la principal,
qué cuenta como servicio activo, qué OT sigue abierta—.
"""

from django import template

from apps.payments.services import customer_debt
from apps.services.models import BillingPolicy, Subscription
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

    # Se traen las suscripciones activas en vez de contarlas: de la misma
    # lista salen el contador y el ciclo de facturación, y contarlas aparte
    # sería una segunda consulta para leer lo mismo.
    active_subscriptions = list(
        Subscription.objects
        .filter(
            customer=customer,
            status=Subscription.Status.ACTIVE,
        )
        .select_related("billing_policy", "address", "address__zone")
    )

    # Si solo existe un servicio activo, la cabecera debe mostrar la
    # ubicación vigente de ese servicio. En abonados con varios servicios no
    # se inventa una dirección única y se conserva la dirección principal.
    if len(active_subscriptions) == 1:
        primary_address = active_subscriptions[0].address

    debt = customer_debt(customer)

    return {
        "customer": customer,
        "primary_address": primary_address,
        "active_service_codes": [
            subscription.service_code
            for subscription in active_subscriptions
            if subscription.service_code
        ],
        "heading_level": heading_level,
        "active_subscription_count": len(active_subscriptions),
        "open_order_count": (
            WorkOrder.objects
            .filter(
                subscription__customer=customer,
                status__in=WorkOrder.ACTIVE_STATUSES,
            )
            .count()
        ),
        "debt_total": debt["total"],
        "billing_cycle_label": _billing_cycle_label(active_subscriptions),
    }


def _billing_cycle_label(subscriptions):
    """Cuándo se le factura al abonado, dicho como se dice en ventanilla.

    Sale de la política de cobro de cada suscripción, que es de donde lo toma
    `monthly_due_date` al emitir la mensualidad. Deducirlo de otro sitio -del
    año del plan, por ejemplo- dejaría la cabecera anunciando un día y el
    cargo venciendo otro el día que un plan cambiara de política, que es
    precisamente lo que la política existe para poder cambiar.

    El ciclo es de cada suscripción y un abonado puede tener varias. Cuando no
    coinciden no se elige una: dar el vencimiento de un servicio como si fuera
    el del abonado diría algo falso de los demás, y la cabecera es justo el
    sitio donde nadie va a ir a comprobarlo.
    """
    labels = {
        _subscription_cycle(subscription)
        for subscription in subscriptions
    }
    labels.discard("")

    if not labels:
        return ""

    if len(labels) == 1:
        return labels.pop()

    return "Varios"


def _subscription_cycle(subscription):
    """El vencimiento mensual de una suscripción, en una línea.

    Las dos ramas son las mismas que `monthly_due_date`, con su misma reserva:
    por aniversario sin fecha de instalación no hay día que anunciar, y el
    cargo acaba venciendo a fin de mes como los demás.
    """
    policy = subscription.billing_policy

    if policy is None:
        return ""

    if (
        policy.billing_mode == BillingPolicy.Mode.ANNIVERSARY
        and subscription.installation_date
    ):
        return f"Día {subscription.installation_date.day} de cada mes"

    return "Fin de mes"
