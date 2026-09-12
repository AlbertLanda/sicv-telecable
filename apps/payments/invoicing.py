"""Lo que el comprobante tiene que decir además de lo que se cobró.

El sistema guarda el dinero como lo entrega el abonado: la mensualidad de
S/ 79 es S/ 79, con el IGV dentro. El papel, en cambio, tiene que abrirlo -
precio sin impuesto, descuento sin impuesto, IGV aparte- porque es lo que la
representación impresa de un comprobante electrónico declara.

Ese desglose vive aquí y no en el dibujo del PDF: es aritmética con reglas de
redondeo propias, y mezclarla con márgenes y tipografías hacía imposible
comprobarla sin abrir un PDF y mirarlo.
"""

from decimal import Decimal, ROUND_HALF_UP


ZERO = Decimal("0.00")

# IGV peruano. Es un tipo de interés del Estado, no una constante del sistema:
# cuando cambie, cambia aquí y el papel entero se recalcula.
IGV_RATE = Decimal("0.18")

# Precio unitario con seis decimales, como en el sistema que se reemplaza: la
# mensualidad de S/ 79 sale de 66.949153 y el redondeo a dos céntimos perdería
# la cifra con la que se puede reconstruir el total.
UNIT_PRICE_PLACES = Decimal("0.000001")
MONEY = Decimal("0.01")


def _round(value, places=MONEY):
    return Decimal(value).quantize(places, rounding=ROUND_HALF_UP)


def net_of_tax(amount):
    """El importe sin IGV. Lo guardado lo lleva dentro."""
    return Decimal(amount) / (Decimal("1") + IGV_RATE)


def receipt_lines(receipt):
    """Una línea por deuda cubierta, con las columnas del papel.

    `Unidad` es SERVICIO en todas: lo que se cobra es el servicio del periodo,
    no unidades de algo. Se escribe igual en vez de dejarla en blanco porque
    la columna existe en el formato y una columna vacía se lee como un dato
    que falta.
    """
    customer = receipt.payment.customer
    lineas = []

    for allocation in receipt.payment.allocations.all():
        charge = allocation.charge

        unitario = _round(net_of_tax(allocation.gross_amount), UNIT_PRICE_PLACES)

        # El total sale de restar el descuento SIN redondear y redondear
        # despues; el descuento que se imprime se deriva de esa resta. Al
        # reves -redondear el descuento y luego restar- la columna se
        # desviaba un centimo por linea, y con tres lineas el recuadro de
        # importes acababa diciendo un sol distinto del que entrego el
        # abonado. Asi, ademas, las tres columnas cuadran por construccion:
        # precio redondeado menos descuento es exactamente el total.
        total = _round(unitario - net_of_tax(allocation.discount))
        descuento = _round(unitario) - total

        descripcion = f"COD {customer.code} {charge.description}"

        if charge.period_label:
            descripcion = f"{descripcion} PERIODO {charge.period_label}"

        lineas.append({
            "quantity": charge.quantity,
            "unit": "SERVICIO",
            "description": descripcion,
            "unit_price": unitario,
            "discount": descuento,
            "total": total,
        })

    return lineas


def receipt_totals(receipt, lines=None):
    """El recuadro de la derecha: base, IGV e importe total.

    El importe total NO se calcula: es el dinero que el abonado entregó y que
    la caja cuadró. Lo que se deriva de él es la base, y el IGV sale de la
    resta, de modo que las tres cifras suman exactamente. Calculando el IGV
    aparte y sumando después, un céntimo de redondeo dejaba el papel diciendo
    S/ 103.99 donde el cajero había recibido S/ 104.00.

    Los céntimos que el redondeo por línea deja sueltos caen en el IGV, que es
    donde caben: la base es la suma de lo que dice cada línea, y el papel
    cuadra columna por columna.
    """
    lines = receipt_lines(receipt) if lines is None else lines
    allocations = list(receipt.payment.allocations.all())

    # Lo aplicado a deuda, no lo recibido: un adelanto que quedó como saldo a
    # favor no se declara en este papel porque todavía no cubrió nada.
    if allocations:
        importe = sum((a.amount for a in allocations), ZERO)
        gravada = sum((linea["total"] for linea in lines), ZERO)
    else:
        importe = receipt.payment.amount
        gravada = _round(net_of_tax(importe))

    return {
        "gravada": gravada,
        "exonerada": ZERO,
        "inafecta": ZERO,
        "gratuita": ZERO,
        "discount": sum((linea["discount"] for linea in lines), ZERO),
        "igv": _round(importe) - gravada,
        "total": _round(importe),
    }


# ------------------------------------------------------------------
# El importe en letras.
#
# «SON: CIENTO CUATRO Y 00/100 SOLES» es la línea que convierte el papel en
# algo que no se puede alterar con un bolígrafo: un 1 delante del 04 se nota
# porque las letras no cuadran.
# ------------------------------------------------------------------

UNIDADES = [
    "", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO",
    "NUEVE", "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE",
    "DIECISÉIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE", "VEINTE",
]

DECENAS = [
    "", "", "VEINTI", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA",
    "SETENTA", "OCHENTA", "NOVENTA",
]

CENTENAS = [
    "", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS",
    "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS",
    "NOVECIENTOS",
]


def _hasta_cien(numero):
    if numero <= 20:
        return UNIDADES[numero]

    decena, unidad = divmod(numero, 10)

    if not unidad:
        return DECENAS[decena]

    # El veintiuno va junto -«VEINTIUNO»- y del treinta en adelante con «Y».
    if decena == 2:
        return f"{DECENAS[2]}{UNIDADES[unidad]}"

    return f"{DECENAS[decena]} Y {UNIDADES[unidad]}"


def _hasta_mil(numero):
    if numero == 100:
        return "CIEN"

    centena, resto = divmod(numero, 100)
    partes = [CENTENAS[centena], _hasta_cien(resto)]

    return " ".join(parte for parte in partes if parte)


def _en_letras(numero):
    if numero == 0:
        return "CERO"

    if numero < 1000:
        return _hasta_mil(numero)

    if numero < 1_000_000:
        miles, resto = divmod(numero, 1000)
        cabeza = "MIL" if miles == 1 else f"{_hasta_mil(miles)} MIL"

        return cabeza if not resto else f"{cabeza} {_hasta_mil(resto)}"

    millones, resto = divmod(numero, 1_000_000)
    cabeza = "UN MILLÓN" if millones == 1 else f"{_en_letras(millones)} MILLONES"

    return cabeza if not resto else f"{cabeza} {_en_letras(resto)}"


def amount_in_words(amount, currency="SOLES"):
    """«CIENTO CUATRO Y 00/100 SOLES».

    Los céntimos van en cifra sobre cien, que es como se escriben en un
    comprobante: deletrearlos alargaría la línea sin hacerla más difícil de
    falsificar.
    """
    entero, centimos = divmod(int(_round(amount) * 100), 100)

    return f"{_en_letras(entero)} Y {centimos:02d}/100 {currency}"
