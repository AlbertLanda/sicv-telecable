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

from apps.payments.models import Issuer, Payment

from .subscriptions import codigo_de_suscripcion


# Quien contrata con el abonado. Es la razón social del contrato firmado que
# ATC entregó como referencia; si alguna sede contrata con otra del grupo, se
# declara en `SEDES`.
ISSUER_CODE = "INV"

# Domicilio legal de la empresa, tal como aparece en el contrato firmado.
DOMICILIO_LEGAL = "Jr. Carlos Arrieta 1443 Dpto. 502, Urb. Santa Beatriz, Lima"


# Lo que cambia por sede. Solo JAUJA está confirmado: sale del contrato
# firmado. La oficina de La Oroya es la que ya figura en la empresa emisora
# cargada en el sistema. Lo que no se sabe se deja vacío a propósito: en el
# papel queda un espacio para completar a mano, que es preferible a imprimir
# una dirección o una jurisdicción inventadas en un documento que se firma.
SEDES = {
    "JAUJA": {
        "offices": (
            "Jr. Abraham Valdelomar 235 – Xauxa, Jauja / "
            "Jr. Huancayo 215 – Jauja"
        ),
        "phone": "064 466080",
        "city": "Jauja",
    },
    "OROYA": {
        "offices": "Av. Miguel Grau 127 – La Oroya",
        "phone": "",
        "city": "La Oroya",
    },
    "HUANCAYO": {
        "offices": "",
        "phone": "",
        "city": "Huancayo",
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

    distrito = (address.district or "").strip()

    return {
        # Identificación del documento
        "numero": contract.contract_number,
        "codigo": str(contract.pk),
        "codigo_abonado": customer.code,

        # La empresa que contrata
        "empresa": empresa_que_contrata(),
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

        # Cuenta de las aplicaciones, solo donde el servicio la pide
        "playhub": (
            (contract.playhub_email, contract.playhub_phone)
            if contract.service_type.requires_playhub_account
            else None
        ),
    }
