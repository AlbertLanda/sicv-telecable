"""Qué suscripción recibe el contrato que se está registrando.

El operador no la elige. Ya la eligió antes, cuando registró la suscripción,
y aquí volvería a decidir lo mismo con menos información delante: servicio y
plan determinan cuál es, y el contrato exige de todos modos que los tres
coincidan. Ofrecerla en un combo solo daba ocasión de equivocarse.

Se resuelve, entonces, a partir de lo que el contrato ya dice: la suscripción
en Preventa de ese cliente, de ese servicio y de ese plan, que todavía no
tenga contrato. Si hay más de una -dos altas del mismo plan en dos
domicilios-, se toma la de menor número de servicio, que es la más antigua.

La pantalla la muestra por su código, como muestra el código del contrato: un
identificador que pone el sistema, en un campo corto y bloqueado.
"""

from apps.services.models import Subscription


# Lo que se muestra cuando el contrato no tiene ninguna suscripción que
# recibirlo. Es la palabra del sistema que se está reemplazando, y dice lo
# justo: el campo está vacío porque no hay nada que poner, no porque falte
# escribirlo.
SIN_SUSCRIPCION = "Ninguno"


def codigo_de_suscripcion(subscription):
    """El código con el que se identifica una suscripción.

    Un código, no una descripción: el contrato lo trata igual que a su
    propio código -un identificador que pone el sistema- y por eso cabe en
    un campo corto. El domicilio y el plan de esa suscripción se leen en la
    ficha, que es donde viven.
    """

    if subscription is None:
        return SIN_SUSCRIPCION

    return subscription.service_code or str(subscription.pk)


def suscripciones_contratables(customer):
    """Las suscripciones del cliente que todavía pueden recibir un contrato.

    En Preventa, activas y sin contrato vigente. Un contrato por suscripción:
    dejar dentro las ya contratadas haría que la resolución eligiera una que
    después el propio contrato rechaza.
    """

    if customer is None:
        return Subscription.objects.none()

    return (
        Subscription.objects
        .filter(
            customer=customer,
            is_active=True,
            status=Subscription.Status.PRESALE,
        )
        .exclude(contracts__is_active=True)
        .select_related("service_type", "plan", "address")
        .order_by("service_number", "pk")
    )


def resolver_suscripcion(customer, service_type, plan, *, subscription_id=None):
    """La suscripción exacta que le toca al contrato, o None.

    Si la pantalla llega desde el resumen de una suscripción, su id manda:
    dos domicilios pueden tener el mismo servicio y plan y no se puede
    adivinar cuál quiso contratar ATC.

    Sin id solo se resuelve automáticamente cuando existe una única
    candidata. La ambigüedad se deja al formulario para mostrar un mensaje
    explícito en lugar de elegir silenciosamente la más antigua.
    """

    if customer is None or service_type is None or plan is None:
        return None

    queryset = suscripciones_contratables(customer).filter(
        service_type=service_type,
        plan=plan,
    )

    if subscription_id:
        return queryset.filter(pk=subscription_id).first()

    candidatas = list(queryset[:2])

    return candidatas[0] if len(candidatas) == 1 else None
