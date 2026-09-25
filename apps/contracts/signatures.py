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

import hashlib
import math
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image as PILImage

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
        .filter(
            subscription_id=order.subscription_id,
            is_active=True,
        )
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


def _ancla_del_documento(contract):
    """Ubicación real de la firma según el PDF que genera el servidor."""

    from .pdf import render_contract

    buffer = BytesIO()
    ancla = {}
    render_contract(
        contract,
        buffer,
        ancla=ancla,
        con_firma=False,
    )

    if not ancla:
        raise ValidationError(
            "No fue posible ubicar el espacio de firma del contrato."
        )

    return ancla


def _proporcion_del_trazo(imagen):
    """alto/ancho del PNG sin depender de medidas enviadas por el navegador."""

    try:
        imagen.open("rb")
    except (AttributeError, TypeError):
        pass

    try:
        contenido = imagen.read()
        imagen.seek(0)
        with PILImage.open(BytesIO(contenido)) as dibujo:
            ancho, alto = dibujo.size
    except Exception as exc:
        raise ValidationError("La firma enviada no es una imagen válida.") from exc

    if not ancho or not alto:
        raise ValidationError("La firma enviada no tiene dimensiones válidas.")

    return alto / ancho


def _validar_colocacion(contract, imagen, colocacion):
    """La firma puede salir de su hueco, pero nunca de la hoja del PDF."""

    colocacion = colocacion or {}

    if not any(
        colocacion.get(campo) is not None
        for campo in ("x", "y", "ancho")
    ):
        return

    ancla = _ancla_del_documento(contract)
    proporcion = _proporcion_del_trazo(imagen)

    ancho_hueco = float(ancla["ancho"])
    alto_hueco = float(ancla["alto"])
    pagina_ancho = float(ancla["pagina_ancho"])
    pagina_alto = float(ancla["pagina_alto"])

    ancho_defecto = min(
        ancho_hueco,
        alto_hueco / proporcion if proporcion else ancho_hueco,
    )

    ancho = float(colocacion.get("ancho") or ancho_defecto)
    alto = ancho * proporcion

    x = colocacion.get("x")
    y = colocacion.get("y")

    x = float(x) if x is not None else (ancho_hueco - ancho) / 2
    y = float(y) if y is not None else 0.0

    valores = (x, y, ancho, alto)
    if not all(math.isfinite(valor) for valor in valores):
        raise ValidationError("La colocación de la firma no es válida.")

    if ancho < 1 or ancho > ancho_hueco * 2.5:
        raise ValidationError(
            "El tamaño de la firma está fuera del rango permitido."
        )

    izquierda = float(ancla["x"]) + x
    derecha = izquierda + ancho
    abajo = float(ancla["y"]) + y
    arriba = abajo + alto

    if (
        izquierda < 0
        or abajo < 0
        or derecha > pagina_ancho
        or arriba > pagina_alto
    ):
        raise ValidationError(
            "La firma debe quedar completamente dentro de la hoja del contrato."
        )


def _archivar_pdf_firmado(firma):
    """Regenera y conserva exactamente el PDF que queda firmado."""

    from .pdf import render_contract

    buffer = BytesIO()
    ancla = {}
    nombre = render_contract(
        firma.contract,
        buffer,
        ancla=ancla,
        con_firma=True,
    )
    contenido = buffer.getvalue()

    anterior = firma.signed_pdf.name
    storage_anterior = firma.signed_pdf.storage

    firma.signed_pdf.save(
        nombre,
        ContentFile(contenido),
        save=False,
    )
    firma.signed_pdf_sha256 = hashlib.sha256(contenido).hexdigest()
    firma.signed_pdf_created_at = timezone.now()
    firma.document_anchor = ancla
    firma.save(
        update_fields=[
            "signed_pdf",
            "signed_pdf_sha256",
            "signed_pdf_created_at",
            "document_anchor",
        ]
    )

    if anterior and anterior != firma.signed_pdf.name:
        storage_anterior.delete(anterior)

    return firma


@transaction.atomic
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

    _validar_colocacion(contract, imagen, colocacion)

    anterior = firma_del_contrato(contract)

    imagen_anterior = ""
    storage_imagen_anterior = None

    if anterior is not None:
        imagen_anterior = anterior.image.name
        storage_imagen_anterior = anterior.image.storage
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
    _archivar_pdf_firmado(firma)

    if (
        imagen_anterior
        and storage_imagen_anterior is not None
        and imagen_anterior != firma.image.name
    ):
        storage_imagen_anterior.delete(imagen_anterior)

    return firma


@transaction.atomic
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
    _validar_colocacion(contract, firma.image, colocacion)

    firma.offset_x = colocacion.get("x")
    firma.offset_y = colocacion.get("y")
    firma.width = colocacion.get("ancho")

    firma.save(update_fields=["offset_x", "offset_y", "width"])
    _archivar_pdf_firmado(firma)

    return firma


@transaction.atomic
def borrar_firma(contract):
    """Descarta la firma registrada. Devuelve si había alguna que borrar.

    Es lo que ocurre cuando el abonado rechaza lo que ve en pantalla: el
    contrato vuelve a su estado sin firmar y la línea sale otra vez en
    blanco, como el papel que nadie firmó.
    """

    firma = firma_del_contrato(contract)

    if firma is None:
        return False

    imagen = firma.image.name
    storage_imagen = firma.image.storage
    pdf = firma.signed_pdf.name
    storage_pdf = firma.signed_pdf.storage

    firma.delete()

    if imagen:
        storage_imagen.delete(imagen)
    if pdf:
        storage_pdf.delete(pdf)

    return True
