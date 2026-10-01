"""El cierre de caja: el consolidado de emisión de una sede.

Es el reporte con el que Contabilidad cuadra la caja en el sistema que se
reemplaza -Reportes › Cierre de caja › «Consolidado de emisión»-, y por eso
repite su hoja fila por fila, con los mismos textos:

    SALDO ANTERIOR
    INGRESOS      Total de Ventas, por tipo de documento y por talonario
    EGRESOS       Garantias, Deposito MN, Gastos RECIBO
    SALDO EN CAJA
    COMPOSICION   billetes, monedas, cheques, vales y otros

Cuatro decisiones que tomó Contabilidad y que el reporte no puede cambiar por
su cuenta:

1. **Solo suman los comprobantes de pagos cancelados.** Un «Cancelado: No»
   imprime el papel pero el dinero todavía no entró, y el saldo en caja tiene
   que ser dinero que está. Los pendientes y los anulados quedan en la
   pestaña de detalle, con su estado.

2. **El periodo se recorta por la emisión del comprobante**, que es lo que
   dice el nombre del reporte. La caja del día, en cambio, recorta por la
   fecha real de pago: son dos preguntas distintas.

3. **Las filas que SICV todavía no registra salen en 0.** No hay gastos,
   depósitos al banco, garantías, otros ingresos ni arqueo, y tampoco
   cierres anteriores de los que sacar el saldo anterior. Se conservan igual
   para que la hoja calce con la de SICAV.

4. **Las series son las de la hoja de SICAV de cada sede**, en su orden, y
   figuran aunque no hayan emitido, en 0. La hoja se lee comparándola con la
   de SICAV, y una serie que desaparece porque no tuvo movimiento obliga a
   adivinar si falta o si no vendió (ver `SICAV_SERIES`).

La sede es siempre una: Contabilidad cuadra cada sede por separado.
"""

import re
from decimal import Decimal

from apps.payments.models import Payment, Receipt, ReceiptSequence


ZERO = Decimal("0.00")


# El desplegable «Reporte». SICAV ofrece más de uno; el que Contabilidad usa
# para cuadrar es el consolidado, y los demás entran cuando se pidan.
REPORT_TYPES = {
    "EMISSION": "Consolidado de emisión",
    "INCOME_BY_USER": "Ingresos por usuario",
}

DEFAULT_REPORT_TYPE = "EMISSION"

REPORT_TYPE_CHOICES = list(REPORT_TYPES.items())

# El único reporte que se pide por usuario (`user_income`). Los demás son de
# la caja entera: en ellos «Usuario» queda bloqueado y no recorta nada, para
# que el consolidado no salga a medias porque quedó elegido un cajero de antes.
USER_REPORT_TYPE = "INCOME_BY_USER"


# Los tres grupos de ingresos, en el orden de la hoja de SICAV.
#
# Se agrupa por el código SUNAT del talonario y no por la letra de la serie:
# los blocks de un cobrador son boletas y su serie empieza por J, M o S, y un
# «S» de cobrador leído por la letra acabaría sumado entre los recibos.
DOCUMENT_GROUPS = [
    (ReceiptSequence.SunatCode.FACTURA, "Facturas"),
    (ReceiptSequence.SunatCode.BOLETA, "Boletas"),
    (ReceiptSequence.SunatCode.RECIBO_SERVICIO, "Recibos de servicios públicos"),
]


# Los egresos de la hoja, escritos como en SICAV -sin tilde-, porque la hoja
# se compara renglón por renglón con la suya. SICV no registra ninguno
# todavía: salen en 0 hasta que existan gastos, depósitos y garantías.
EXPENSE_LABELS = ["Garantias", "Deposito MN", "Gastos RECIBO"]


# Las series que lista la hoja de SICAV en cada sede, en su orden, con la
# empresa emisora de cada una (por su código de `Issuer`).
#
# Salen de las hojas que exporta SICAV (septiembre de 2026) y no del padrón de
# talonarios de SICV, por dos razones:
#
# - El padrón decide qué ofrece cada ventanilla al cobrar. Recortarlo o
#   ampliarlo para que el reporte calce cambiaría lo que el cajero puede
#   emitir.
# - No coinciden: SICAV lista series que SICV todavía no tiene dadas de alta
#   -en Jauja, las facturas de INVERSIONES 003 o los recibos 012- y SICV tiene
#   talonarios que la hoja de SICAV no trae.
#
# Una serie de la lista sin talonario en SICV sale igual, en 0. Un talonario
# que emite y no está en la lista se agrega al final de su grupo: ningún
# monto puede quedar fuera del total de ventas.
#
# Una sede sin lista -La Oroya, hasta tener su hoja de SICAV- lista los
# talonarios de su padrón (ver `listed_sequences`).
_F = ReceiptSequence.SunatCode.FACTURA
_B = ReceiptSequence.SunatCode.BOLETA
_R = ReceiptSequence.SunatCode.RECIBO_SERVICIO

SICAV_SERIES = {
    "JAUJA": [
        (_F, "CABLE LOS ANDES", "001", "CLA"),
        (_F, "INVERSIONES", "002", "INV"),
        (_F, "INVERSIONES", "003", "INV"),
        (_B, "CABLE LOS ANDES", "001", "CLA"),
        (_B, "INVERSIONES", "002", "INV"),
        (_B, "CABLE LOS ANDES", "003", "CLA"),
        (_B, "INVERSIONES", "003", "INV"),
        (_B, "INVERSIONES", "004", "INV"),
        (_B, "CABLE LOS ANDES", "004", "CLA"),
        (_R, "RED OPTICA", "011", "ROP"),
        (_R, "SPEEDY", "011", "SPQ"),
        (_R, "RED OPTICA", "012", "ROP"),
        (_R, "SPEEDY", "012", "SPQ"),
        (_R, "VELOCIDAD", "012", "VEL"),
    ],
    "HUANCAYO": [
        (_F, "CABLE LOS ANDES", "001", "CLA"),
        (_F, "INVERSIONES", "002", "INV"),
        (_B, "CABLE LOS ANDES", "001", "CLA"),
        (_B, "INVERSIONES", "002", "INV"),
        (_B, "CABLE LOS ANDES", "003", "CLA"),
        (_B, "INVERSIONES", "006", "INV"),
        (_B, "INVERSIONES", "007", "INV"),
        (_R, "RED OPTICA", "003", "ROP"),
        (_R, "SPEEDY", "003", "SPQ"),
        (_R, "SPEEDY", "009", "SPQ"),
        (_R, "RED OPTICA", "009", "ROP"),
        (_R, "RED OPTICA", "012", "ROP"),
        (_R, "SPEEDY", "012", "SPQ"),
        (_R, "VELOCIDAD", "012", "VEL"),
    ],
}


# La composición del saldo en caja: el arqueo. SICV no lo registra todavía,
# así que cada fila sale en 0.
COMPOSITION_LABELS = [
    "Billetes de 200",
    "Billetes de 100",
    "Billetes de 50",
    "Billetes de 20",
    "Billetes de 10",
    "Monedas",
    "Cheques",
    "Vales Personal",
    "Otros",
]


# El detalle, una fila por comprobante: la pestaña «Detalle» del Excel.
DETAIL_COLUMNS = [
    {"key": "issued_at", "label": "Emisión", "width": 16},
    {"key": "receipt", "label": "Comprobante", "width": 14},
    {"key": "series_label", "label": "Talonario", "width": 26},
    {"key": "issuer", "label": "Empresa", "width": 26},
    {"key": "customer_code", "label": "Código", "width": 10},
    {"key": "customer_name", "label": "Abonado", "width": 28},
    {"key": "office", "label": "Oficina", "width": 20},
    {"key": "method", "label": "Método", "width": 13},
    {"key": "reference", "label": "Referencia", "width": 16},
    {"key": "paid_at", "label": "Pago real", "width": 16},
    {"key": "amount", "label": "Monto", "width": 12, "numeric": True},
    {"key": "status", "label": "Estado", "width": 11},
    {"key": "received_by", "label": "Usuario", "width": 18},
    {"key": "collector", "label": "Cobrador", "width": 18},
]


_LETTER_AND_NUMBER = re.compile(r"[A-Za-z](\d+)")

# La forma societaria al final de una razón social: «S.A.C.», «E.I.R.L.»,
# «SAC», «EIRL»... La hoja nombra la marca, no la sociedad.
_LEGAL_SUFFIX = re.compile(
    r"\s+(S\.?A\.?C\.?|S\.?A\.?A\.?|S\.?A\.?|E\.?I\.?R\.?L\.?|S\.?R\.?L\.?)$",
    re.IGNORECASE,
)


def series_name(sequence):
    """El talonario como lo nombra la hoja de SICAV: «VELOCIDAD - 010».

    La marca sale de la etiqueta del talonario -«S:S010 - VELOCIDAD»- y no de
    la empresa emisora, porque la hoja las distingue por marca: VELOCIDAD, RED
    OPTICA y SPEEDY son tres líneas aunque las tres imprimieran «S010». El
    número va sin la letra de la serie, que en la hoja ya dice el grupo.

    Un talonario sin marca en la etiqueta usa la razón social de su emisora,
    sin la forma societaria: la hoja dice «CABLE LOS ANDES», no «CABLE LOS
    ANDES S.A.C.».

    Una serie que no es letra y número -«V.COND», el «JU1» de un cobrador- se
    escribe entera: recortarla la dejaría irreconocible.
    """
    label = sequence.label or ""

    if " - " in label:
        brand = label.split(" - ", 1)[1].strip()
    elif sequence.issuer_id:
        brand = _LEGAL_SUFFIX.sub("", sequence.issuer.business_name.strip())
    else:
        brand = label or sequence.series

    match = _LETTER_AND_NUMBER.fullmatch(sequence.series or "")
    number = match.group(1) if match else sequence.series

    return f"{brand} - {number}"


def series_label(sequence):
    """La línea de la hoja de SICAV: «Serie VELOCIDAD - 010»."""
    return f"Serie {series_name(sequence)}"


def _series_sort_key(sequence):
    """Por número de serie y luego por marca: el orden de las series que la
    hoja no trae en una lista fija."""
    match = _LETTER_AND_NUMBER.fullmatch(sequence.series or "")

    return (
        int(match.group(1)) if match else 10**6,
        series_label(sequence),
    )


def sicav_series(*, branch, issuer=None, sequence=None):
    """Las series de la hoja de SICAV de la sede, ya recortadas por filtros.

    Devuelve None si la sede no tiene lista. Con «Empresa» elegida quedan
    solo las de esa empresa, y con «Serie» elegida solo la que corresponde a
    ese talonario.
    """
    rows = SICAV_SERIES.get(branch.code)

    if rows is None:
        return None

    selected = []

    for code, brand, number, issuer_code in rows:
        name = f"{brand} - {number}"

        if issuer is not None and issuer.code != issuer_code:
            continue

        if sequence is not None and (
            sequence.sunat_code != code or series_name(sequence) != name
        ):
            continue

        selected.append((code, name))

    return selected


def listed_sequences(*, branch, office=None, issuer=None, sequence=None):
    """Los talonarios que la hoja lista aunque no hayan emitido.

    Son los que ofrecen las oficinas activas de la sede -o solo la oficina,
    sin «Consolidado oficinas»-, que es el padrón de talonarios que la sede
    tiene en el cajón. Los retirados no se listan, y los blocks de un cobrador
    tampoco: se ofrecen en todas las oficinas de todas las sedes, y la hoja de
    SICAV no los trae. Unos y otros aparecen igual en cuanto emiten algo en el
    periodo, porque entonces tienen monto que mostrar.

    El block de un cobrador se reconoce porque no numera solo (`autonumber`):
    es papel que él ya trae numerado.
    """
    # Los dos requisitos de la oficina van en un solo `filter`: separados,
    # Django los resolvería con dos uniones distintas y bastaría con que el
    # talonario estuviera en una oficina activa de otra sede y en una oficina
    # cerrada de esta.
    if office is not None:
        where_offered = {
            "office_links__office": office,
            "office_links__office__is_active": True,
        }
    else:
        where_offered = {
            "office_links__office__branch": branch,
            "office_links__office__is_active": True,
        }

    sequences = ReceiptSequence.objects.select_related("issuer").filter(
        is_active=True,
        autonumber=True,
        **where_offered,
    )

    if issuer is not None:
        sequences = sequences.filter(issuer=issuer)

    if sequence is not None:
        sequences = sequences.filter(pk=sequence.pk)

    return sequences.distinct()


def period_receipts(
    *,
    branch,
    date_from,
    date_to,
    office=None,
    issuer=None,
    sequence=None,
    user=None,
):
    """Los comprobantes emitidos en el periodo, en cualquier estado.

    Trae también los de pagos pendientes y anulados: el consolidado no los
    suma, pero el detalle los lista con su estado. El recorte de estado se
    hace al sumar, en un solo sitio, para que el total y el detalle no puedan
    contar cosas distintas.

    Las dos fechas son inclusivas y se leen en la hora de Lima.
    """
    receipts = (
        Receipt.objects
        .select_related(
            "sequence",
            "sequence__issuer",
            "payment",
            "payment__customer",
            "payment__office",
            "payment__received_by",
            "payment__collector",
        )
        .filter(
            payment__branch=branch,
            issued_at__date__gte=date_from,
            issued_at__date__lte=date_to,
        )
    )

    if office is not None:
        receipts = receipts.filter(payment__office=office)

    if issuer is not None:
        receipts = receipts.filter(sequence__issuer=issuer)

    if sequence is not None:
        receipts = receipts.filter(sequence=sequence)

    if user is not None:
        receipts = receipts.filter(payment__received_by=user)

    return receipts.order_by("issued_at", "pk")


def _person(user):
    if user is None:
        return ""

    return user.get_full_name() or user.username


def _detail_row(receipt):
    payment = receipt.payment
    customer = payment.customer
    issuer = receipt.sequence.issuer

    return {
        "issued_at": receipt.issued_at,
        "receipt": receipt.full_number,
        "series_label": series_label(receipt.sequence),
        "issuer": issuer.business_name if issuer else "",
        "customer_code": customer.code,
        "customer_name": str(customer),
        "office": payment.office.name if payment.office_id else "",
        "method": payment.get_method_display(),
        "reference": payment.reference,
        "paid_at": payment.paid_at,
        "amount": payment.amount,
        "status": payment.get_status_display(),
        "status_code": payment.status,
        "received_by": _person(payment.received_by),
        "collector": _person(payment.collector),
    }


def _line(text, amount, style):
    """Una fila de la hoja: su texto como lo escribe SICAV -«. Facturas:»-,
    su monto y su estilo (sección, fila, grupo, serie, total, saldo o una
    fila en blanco)."""
    return {"text": text, "amount": amount, "style": style}


def _summary_lines(report):
    """Las filas de la hoja, en el orden exacto de SICAV.

    Las secciones no llevan monto. El Excel y el PDF recorren esta misma
    lista, así que una fila nueva aparece en los dos o en ninguno.
    """
    lines = [
        _line("SALDO ANTERIOR", None, "section"),
        _line("Total:", report["opening_balance"], "item"),
        _line("INGRESOS", None, "section"),
        _line("Total de Ventas:", report["sales_total"], "item"),
    ]

    for group in report["groups"]:
        lines.append(_line(f". {group['label']}:", group["total"], "group"))

        for line in group["lines"]:
            lines.append(_line(f".. {line['label']} :", line["total"], "series"))

    lines.extend([
        _line("Garantias:", report["guarantees"], "item"),
        _line("Otros:", report["other_income"], "item"),
        _line("... TOTAL:", report["income_total"], "total"),
        _line("EGRESOS", None, "section"),
    ])

    for expense in report["expenses"]:
        lines.append(_line(f"(-){expense['label']}:", expense["total"], "item"))

    lines.extend([
        _line("... TOTAL:", report["expense_total"], "total"),
        _line("SALDO EN CAJA:", report["cash_balance"], "balance"),
        _line("", None, "blank"),
        _line("COMPOSICION", None, "section"),
    ])

    for item in report["composition"]:
        lines.append(_line(item["label"], item["total"], "item"))

    lines.append(_line("... TOTAL", report["composition_total"], "total"))

    return lines


def build_cash_closing(
    *,
    branch,
    date_from,
    date_to,
    office=None,
    issuer=None,
    sequence=None,
    user=None,
    report_type=DEFAULT_REPORT_TYPE,
    printed_by="",
):
    """Todo lo que el PDF y el Excel necesitan para imprimirse."""
    receipts = list(
        period_receipts(
            branch=branch,
            date_from=date_from,
            date_to=date_to,
            office=office,
            issuer=issuer,
            sequence=sequence,
            user=user,
        )
    )

    by_group = {code: {} for code, _label in DOCUMENT_GROUPS}
    pending = {"operations": 0, "total": ZERO}
    voided = {"operations": 0, "total": ZERO}

    # Las filas se identifican por el nombre de la serie -«INVERSIONES -
    # 002»- y no por el talonario: es como las nombra la hoja de SICAV, y una
    # fila de su lista puede no tener talonario en SICV.
    def add_row(code, name, sort):
        # Sin `setdefault` sobre el grupo a propósito: un tipo de documento
        # nuevo que no tenga grupo en la hoja tiene que fallar aquí, no quedar
        # fuera del total de ventas sin que nadie lo note.
        return by_group[code].setdefault(
            name,
            {
                "label": f"Serie {name}",
                "operations": 0,
                "total": ZERO,
                "sort": sort,
            },
        )

    def line_for(talonario):
        # Lo que no está en la lista de SICAV va al final de su grupo.
        return add_row(
            talonario.sunat_code,
            series_name(talonario),
            (1,) + _series_sort_key(talonario),
        )

    fixed = sicav_series(branch=branch, issuer=issuer, sequence=sequence)

    if fixed is not None:
        for position, (code, name) in enumerate(fixed):
            add_row(code, name, (0, position))
    else:
        for talonario in listed_sequences(
            branch=branch, office=office, issuer=issuer, sequence=sequence
        ):
            line_for(talonario)

    for receipt in receipts:
        status = receipt.payment.status
        amount = receipt.payment.amount

        if status == Payment.Status.PENDING:
            pending["operations"] += 1
            pending["total"] += amount
            continue

        if status == Payment.Status.VOIDED:
            voided["operations"] += 1
            voided["total"] += amount
            continue

        line = line_for(receipt.sequence)
        line["operations"] += 1
        line["total"] += amount

    groups = []

    for code, label in DOCUMENT_GROUPS:
        lines = sorted(by_group[code].values(), key=lambda row: row["sort"])
        groups.append({
            "code": code,
            "label": label,
            "lines": lines,
            "operations": sum(line["operations"] for line in lines),
            "total": sum((line["total"] for line in lines), ZERO),
        })

    sales_total = sum((group["total"] for group in groups), ZERO)
    opening_balance = ZERO
    guarantees = ZERO
    other_income = ZERO
    income_total = sales_total + guarantees + other_income

    expenses = [{"label": label, "total": ZERO} for label in EXPENSE_LABELS]
    expense_total = sum((expense["total"] for expense in expenses), ZERO)

    composition = [{"label": label, "total": ZERO} for label in COMPOSITION_LABELS]

    report = {
        "title": "Control administrativo emisión",
        "report_type": report_type,
        "report_type_label": REPORT_TYPES.get(
            report_type, REPORT_TYPES[DEFAULT_REPORT_TYPE]
        ),
        "branch": branch,
        "office": office,
        "place_label": str(office) if office is not None else branch.name,
        "date_from": date_from,
        "date_to": date_to,
        "printed_by": printed_by,
        "opening_balance": opening_balance,
        "groups": groups,
        "sales_total": sales_total,
        "guarantees": guarantees,
        "other_income": other_income,
        "income_total": income_total,
        "expenses": expenses,
        "expense_total": expense_total,
        "cash_balance": opening_balance + income_total - expense_total,
        "composition": composition,
        "composition_total": sum(
            (item["total"] for item in composition), ZERO
        ),
        "operations": sum(group["operations"] for group in groups),
        "pending": pending,
        "voided": voided,
        "columns": DETAIL_COLUMNS,
        "rows": [_detail_row(receipt) for receipt in receipts],
    }
    report["lines"] = _summary_lines(report)

    return report
