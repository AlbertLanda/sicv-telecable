"""Los datos de la empresa que van impresos en el contrato de abonado.

El contrato que firma el abonado no es solo lo que el SICV registra: es un
documento con partes fijas -las cláusulas, la razón social que contrata, las
oficinas donde se reclama, la ciudad cuyos tribunales resuelven- y huecos que
se llenan con el cliente y su plan.

Las partes fijas viven aquí y no en la plantilla porque cambian por sede: el
contrato de Jauja somete las controversias a los tribunales de Jauja, y el de
otra sede a los suyos. Repetir el texto por sede en el HTML dejaría tres
copias que se separan al primer ajuste legal.

La razón social sale de las empresas emisoras que ya están cargadas en el
sistema -las mismas con las que se factura-, no de una constante: el RUC de
la empresa no puede vivir en dos sitios distintos.

Aquí se resuelve *qué* dice el papel; en `pdf.py` se dibuja *cómo* se ve. Esa
separación es la que permite comprobar los datos del contrato sin abrir un
PDF y mirarlo, igual que cobranza comprueba su aritmética aparte del dibujo
del comprobante.
"""

from apps.organization import branding
from apps.payments.models import Issuer, Payment

from .signatures import firma_del_contrato
from .subscriptions import codigo_de_suscripcion


# Quien contrata con el abonado. Es la razón social del contrato firmado que
# ATC entregó como referencia; si alguna sede contrata con otra del grupo, se
# declara en `SEDES`.
ISSUER_CODE = "INV"

# Domicilio legal de la empresa, tal como aparece en el contrato firmado.
DOMICILIO_LEGAL = "Jr. Carlos Arrieta 1443 Dpto. 502, Urb. Santa Beatriz, Lima"


# Lo que cambia por sede. Las tres salen de los contratos oficiales que
# entregó administración -uno por sede-, así que aquí no hay nada deducido:
# las oficinas comerciales son las que el papel lista, y la ciudad es la de
# la jurisdicción que ese mismo papel declara.
#
# `city` gobierna tres sitios del documento -el subtítulo del título, los
# tribunales de la cláusula undécima y la ciudad donde se suscribe-, y por eso
# no siempre coincide con el nombre de la sede: La Oroya contrata y litiga
# como «Yauli – La Oroya».
#
# Una sede que no esté aquí imprime esos espacios en blanco a propósito: en un
# documento que se firma, un hueco para completar a mano es preferible a una
# dirección o una jurisdicción inventadas.
SEDES = {
    "JAUJA": {
        "offices": (
            "Jr. Abraham Valdelomar 235 – Xauxa, Jauja / "
            "Jr. Huancayo 215 – Jauja"
        ),
        "phone": "064 466080",
        "city": "Jauja",
    },
    "HUANCAYO": {
        "offices": (
            "Jr. Huaytapallana 214 – El Tambo, Huancayo / "
            "Calle Real 1147 Stand N° 6 – Sicaya, Huancayo"
        ),
        "phone": "064 466080",
        "city": "Huancayo",
    },
    "OROYA": {
        "offices": (
            "AV. Miguel Grau 1025 – Marcavalle - Santa Rosa de Saccos, "
            "Yauli – La Oroya"
        ),
        "phone": "064 466080",
        "city": "Yauli – La Oroya",
    },
}


MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "setiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def mes_en_palabras(fecha):
    """El mes escrito, como lo pide el cierre del contrato."""

    if fecha is None:
        return ""

    return MESES[fecha.month - 1]


def empresa_que_contrata():
    """La razón social y el RUC que salen impresos.

    Si la empresa emisora no está cargada -una base recién migrada, sin el
    catálogo de cobranza-, se devuelve `None` y la pantalla lo dice en vez de
    imprimir un contrato sin quién lo firma.
    """

    return Issuer.objects.filter(code=ISSUER_CODE).first()


def sello_de_la_empresa(empresa):
    """La firma de quien contrata, ya estampada en el documento.

    El abonado firma en el móvil del técnico; la empresa no: su firma es
    siempre la misma y va impresa, como en los contratos que se entregaban
    en papel con el sello puesto.

    El archivo lo deja administración en MEDIA_ROOT, uno por código de
    empresa emisora (`firma_INV.png`), y tiene que ser un **PNG recortado y
    con fondo transparente**: el sello se apoya sobre la línea de firma, y un
    fondo blanco la taparía dejando el recuadro a la vista.

    Una razón social sin firma cargada devuelve `None`, y el contrato sale
    con su espacio en blanco para firmarlo a mano. Es la misma regla que el
    resto del documento: lo que no se sabe se deja en blanco, no se inventa.
    """

    if empresa is None:
        return None

    archivo = branding.buscar_imagen(branding.stem_de_la_firma(empresa.code))

    if archivo is None:
        return None

    return archivo.read_bytes()


def datos_de_la_sede(branch):
    """Oficinas, teléfono y ciudad de la jurisdicción de una sede.

    Una sede sin datos confirmados devuelve los campos vacíos y la ciudad con
    su propio nombre: el documento se imprime igual, con el espacio en blanco
    a la vista, y quien lo revise sabe qué falta configurar.
    """

    if branch is None:
        return {"offices": "", "phone": "", "city": ""}

    datos = SEDES.get(branch.code)

    if datos is None:
        return {"offices": "", "phone": "", "city": branch.name}

    return dict(datos)


def ultima_fecha_de_pago(customer):
    """La del último cobro registrado, o nada si nunca pagó.

    El contrato firmado la trae en blanco al momento de la venta, y así sale
    también aquí: no hay nada que imprimir todavía.
    """

    return (
        Payment.objects
        .filter(customer=customer)
        .order_by("-received_at")
        .values_list("received_at", flat=True)
        .first()
    )


def firma_del_abonado(contract):
    """El trazo que el abonado firmó en campo, listo para dibujarlo.

    Se devuelven los **bytes** y no el archivo: el dibujo no tiene por qué
    saber en qué storage vive la firma, igual que no sabe de dónde sale la
    razón social. Un contrato sin firmar devuelve `None` y el papel imprime
    la línea en blanco de siempre, que es lo que hay que llevar a firmar.
    """

    firma = firma_del_contrato(contract)

    if firma is None or not firma.image:
        return None

    with firma.image.open("rb") as archivo:
        contenido = archivo.read()

    return {
        "imagen": contenido,
        "firmante": firma.signer_name,
        "fecha": firma.signed_at,
        "colocacion": firma.colocacion,
    }


def datos_del_contrato(contract):
    """Todo lo que el papel del contrato necesita, ya resuelto.

    Un diccionario y no el contrato en bruto: el dibujo no tiene por qué
    saber que la dirección de instalación vive en la suscripción, ni que la
    razón social sale del catálogo de cobranza. Y así los datos se comprueban
    en una prueba corta, sin abrir el PDF para leerlos.
    """

    customer = contract.customer
    subscription = contract.subscription
    address = subscription.address
    plan = contract.plan

    sede = datos_de_la_sede(customer.branch)
    empresa = empresa_que_contrata()

    distrito = (address.district or "").strip()

    return {
        # Identificación del documento
        "numero": contract.contract_number,
        "codigo": str(contract.pk),
        "codigo_abonado": customer.code,

        # La empresa que contrata
        "empresa": empresa,
        "domicilio_legal": DOMICILIO_LEGAL,
        "oficinas": sede["offices"],
        "telefono": sede["phone"],
        "ciudad": sede["city"],

        # El abonado
        "cliente": str(customer),
        "documento_tipo": customer.get_document_type_display(),
        "documento_numero": customer.document_number,
        "direccion": (
            f"{address.address}, {distrito}" if distrito else address.address
        ),

        # Lo contratado
        "servicio": f"{contract.service_type} – {plan}",
        "suscripcion": codigo_de_suscripcion(subscription),
        "velocidad": plan.speed_mbps,
        "instalacion": subscription.base_installation_fee,
        "mensualidad": subscription.base_monthly_fee,

        # Fechas
        "fecha_suscripcion": contract.start_date,
        "ultima_fecha_de_pago": ultima_fecha_de_pago(customer),
        "dia": contract.start_date.day if contract.start_date else "",
        "mes": mes_en_palabras(contract.start_date),
        "anio": contract.start_date.year if contract.start_date else "",

        # Las dos firmas: la del abonado se recoge en campo, la de la
        # empresa va impresa siempre.
        "firma_abonado": firma_del_abonado(contract),
        "firma_empresa": sello_de_la_empresa(empresa),

        # Cuenta de las aplicaciones, solo donde el servicio la pide
        "playhub": (
            (contract.playhub_email, contract.playhub_phone)
            if contract.service_type.requires_playhub_account
            else None
        ),
    }
