"""La firma del abonado sobre su contrato.

El abonado firma en el móvil del técnico, en su domicilio, mientras se
instala el servicio. Lo que se guarda es el **trazo**, no un PDF firmado: el
contrato se dibuja siempre desde sus datos, así que archivar un documento
aparte crearía una segunda versión del mismo contrato que podría dejar de
coincidir con la primera. Con el trazo guardado, el contrato firmado es el
de siempre con un dato más, y sale igual por el portal del técnico que por
SICV.

Aquí vive lo que la firma es -de qué contrato, con qué imagen, quién la
recogió y cuándo- sin saber nada del canal por el que llega. Qué orden puede
recogerla y en qué estado lo decide `work_orders`, que es donde se sabe.
"""

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Contract, ContractSignature


# El trazo de una firma es un dibujo de pocas decenas de KB. El límite está
# para que un archivo cualquiera renombrado no entre por el canal del
# técnico, no para ajustar la calidad del trazo.
TAMANO_MAXIMO_BYTES = 2 * 1024 * 1024


def contrato_de_la_orden(order):
    """El contrato que ampara la orden, o `None` si la venta no lo tiene.

    Se llega por la suscripción, que es lo que la orden y el contrato
    comparten: el contrato es el respaldo comercial de esa suscripción y la
    orden, su instalación. Es un contrato por suscripción -lo garantiza la
    resolución del alta-, así que la consulta devuelve uno; si una base
    antigua trajera dos, se toma el último registrado, que es el vigente.
    """

    if order.subscription_id is None:
        return None

    return (
        Contract.objects
        .filter(subscription_id=order.subscription_id)
        .select_related(
            "customer",
            "customer__branch",
            "service_type",
            "plan",
            "subscription",
            "subscription__address",
        )
        .order_by("-created_at")
        .first()
    )


def firma_del_contrato(contract):
    """La firma registrada, o `None` mientras el abonado no haya firmado."""

    return ContractSignature.objects.filter(contract=contract).first()


def firmar_contrato(contract, imagen, *, usuario=None, orden=None, colocacion=None):
    """Registra -o rehace- la firma del abonado sobre el contrato.

    Rehacer reemplaza: el abonado firma una vez y lo que vale es el trazo que
    aceptó, no el historial de intentos. El archivo anterior se borra en el
    mismo paso, porque un trazo descartado de una persona no tiene por qué
    seguir guardado.

    El nombre del firmante se **copia** del abonado en este momento en lugar
    de leerse del cliente al imprimir: el papel dice quién firmó ese día.

    `colocacion` es dónde dejó el trazo quien firmó -{"x", "y", "ancho"} en
    puntos, dentro del hueco de firma-. Sin ella, la firma va centrada sobre
    la línea, que es donde el papel la pone por su cuenta.
    """

    if not imagen:
        raise ValidationError("Debe dibujar la firma del abonado.")

    tamano = getattr(imagen, "size", None)
    if tamano is not None and tamano > TAMANO_MAXIMO_BYTES:
        raise ValidationError(
            "La firma supera el tamaño permitido. Vuelva a dibujarla."
        )

    anterior = firma_del_contrato(contract)

    if anterior is not None:
        anterior.image.delete(save=False)
        firma = anterior
    else:
        firma = ContractSignature(contract=contract)

    # Dónde la dejó el técnico. Sin ajuste, los tres campos vuelven a vacío:
    # una firma rehecha empieza centrada sobre la línea, como la primera.
    colocacion = colocacion or {}
    firma.offset_x = colocacion.get("x")
    firma.offset_y = colocacion.get("y")
    firma.width = colocacion.get("ancho")

    firma.image = imagen
    firma.signer_name = str(contract.customer)
    firma.work_order = orden
    firma.captured_by = usuario
    firma.signed_at = timezone.now()

    firma.full_clean(exclude=["contract", "work_order", "captured_by"])
    firma.save()

    return firma


def mover_firma(contract, colocacion):
    """Cambia dónde va el trazo, sin volver a pedirle al abonado que firme.

    Recolocar no es firmar otra vez: el trazo sigue siendo el que hizo, y lo
    que cambia es dónde se apoya en la hoja. Por eso no se toca `signed_at`
    ni el firmante -el abonado firmó cuando firmó- y no hace falta que
    vuelva a estar delante.
    """

    firma = firma_del_contrato(contract)

    if firma is None:
        raise ValidationError("Este contrato todavía no está firmado.")

    colocacion = colocacion or {}

    firma.offset_x = colocacion.get("x")
    firma.offset_y = colocacion.get("y")
    firma.width = colocacion.get("ancho")

    firma.save(update_fields=["offset_x", "offset_y", "width"])

    return firma


def borrar_firma(contract):
    """Descarta la firma registrada. Devuelve si había alguna que borrar.

    Es lo que ocurre cuando el abonado rechaza lo que ve en pantalla: el
    contrato vuelve a su estado sin firmar y la línea sale otra vez en
    blanco, como el papel que nadie firmó.
    """

    firma = firma_del_contrato(contract)

    if firma is None:
        return False

    firma.image.delete(save=False)
    firma.delete()
    return True
