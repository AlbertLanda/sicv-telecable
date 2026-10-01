"""Reportes › Cierre de caja › «Ingresos por usuario».

Es el «Reporte de ingresos» de SICAV: una fila por concepto cobrado -no por
comprobante-, con quién lo registró y el total al pie. Un comprobante que
cubrió tres conceptos ocupa tres filas, como en la hoja de SICAV.

Las reglas son las del consolidado (`cash_closing`), para que los dos cuadren
entre sí: solo suman los pagos cancelados y el periodo se recorta por la
emisión del comprobante. Con los mismos filtros, el total de este reporte es
el Total de Ventas del consolidado.

Sin usuario elegido salen todos los que registraron cobros, como hace SICAV
con «NINGUNO», y el título lo dice con «Usuarios».
"""

from decimal import Decimal

from django.db.models import Prefetch
from django.utils import timezone

from apps.customers.models import Customer, CustomerAddress
from apps.payments.models import Payment

from .cash_closing import period_receipts


ZERO = Decimal("0.00")

# Lo que un pago recibió de más y todavía no cubre ningún cargo. Va en su
# propia fila para que el total siga siendo el dinero que entró: sin ella, el
# total de este reporte y el Total de Ventas del consolidado no cuadrarían.
UNALLOCATED_DETAIL = "Saldo a favor"

# Las columnas de la hoja de SICAV, en su orden. Las salidas recorren esta
# lista, así que una columna nueva aparece en el Excel y en el PDF a la vez.
COLUMNS = [
    {"key": "customer_code", "label": "Código", "width": 17},
    {"key": "issued_on", "label": "Fecha", "width": 11, "date": True},
    {"key": "customer_name", "label": "Abonado", "width": 30},
    {"key": "address", "label": "Dirección", "width": 35},
    {"key": "paid_on", "label": "Fecha pago", "width": 11, "date": True},
    {"key": "detail", "label": "Detalle", "width": 30},
    {"key": "paid_until", "label": "Pagó hasta", "width": 11, "date": True},
    {"key": "amount", "label": "Monto", "width": 11, "numeric": True},
    {"key": "document", "label": "Documento", "width": 18},
    {"key": "user", "label": "Usuario", "width": 14},
]


def customer_name(customer):
    """«APELLIDOS, NOMBRES», como lo escribe la hoja de SICAV. Una empresa va
    con su razón social."""
    if customer.person_type == Customer.PersonType.LEGAL:
        return customer.business_name or customer.document_number

    surnames = " ".join(
        filter(None, [customer.paternal_surname, customer.maternal_surname])
    )

    if surnames and customer.first_name:
        return f"{surnames}, {customer.first_name}"

    return surnames or customer.first_name or customer.document_number


def _document_letter(receipt):
    """La letra con que SICAV nombra el talonario: la «B» de «B:B007 - MARCA».

    Sale de la etiqueta porque es donde el padrón la guarda. Un talonario sin
    letra en la etiqueta -«V.COND - ALFA»- no la lleva.
    """
    head = (receipt.sequence.label or "").split(" - ", 1)[0]

    if ":" not in head:
        return ""

    return head.split(":", 1)[0].strip()


def document_label(receipt):
    """La columna «Documento»: «B:B007 0000067».

    La serie es la del comprobante y no la del talonario: es la que quedó
    impresa, aunque el talonario se haya reetiquetado después.
    """
    letter = _document_letter(receipt)
    prefix = f"{letter}:" if letter else ""

    return f"{prefix}{receipt.series} {receipt.printed_number}"


def _document_sort_key(receipt):
    # Como la hoja de SICAV: por talonario y, dentro de él, por número, de
    # modo que las filas de un mismo comprobante quedan juntas.
    return (_document_letter(receipt), receipt.series, receipt.number, receipt.pk)


def _local_date(moment):
    if moment is None:
        return None

    return timezone.localtime(moment).date()


def _receipt_rows(receipt):
    """Las filas de un comprobante: una por cargo que cubrió, y el saldo a
    favor si el pago trajo más de lo que aplicó."""
    payment = receipt.payment
    customer = payment.customer
    addresses = customer.primary_addresses

    common = {
        "customer_code": customer.code,
        "issued_on": _local_date(receipt.issued_at),
        "customer_name": customer_name(customer),
        "address": addresses[0].address if addresses else "",
        "paid_on": _local_date(payment.paid_at),
        "document": document_label(receipt),
        "user": payment.received_by.username,
    }

    rows = []
    applied = ZERO

    for allocation in payment.allocations.all():
        charge = allocation.charge
        applied += allocation.amount

        rows.append({
            **common,
            "detail": charge.description,
            # Hasta dónde quedó cubierto el servicio con ese cargo. Un cargo
            # sin periodo -una reconexión, un anexo suelto- no cubre días.
            "paid_until": charge.period_end,
            "amount": allocation.amount,
        })

    remainder = payment.amount - applied

    if remainder > ZERO:
        rows.append({
            **common,
            "detail": UNALLOCATED_DETAIL,
            "paid_until": None,
            "amount": remainder,
        })

    return rows


def build_user_income(
    *,
    branch,
    date_from,
    date_to,
    office=None,
    issuer=None,
    sequence=None,
    user=None,
):
    """Todo lo que el PDF y el Excel del reporte necesitan para imprimirse."""
    receipts = (
        period_receipts(
            branch=branch,
            date_from=date_from,
            date_to=date_to,
            office=office,
            issuer=issuer,
            sequence=sequence,
            user=user,
        )
        .filter(payment__status=Payment.Status.REGISTERED)
        .prefetch_related(
            "payment__allocations__charge",
            Prefetch(
                "payment__customer__addresses",
                queryset=CustomerAddress.objects.filter(is_primary=True),
                to_attr="primary_addresses",
            ),
        )
    )

    rows = []

    for receipt in sorted(receipts, key=_document_sort_key):
        rows.extend(_receipt_rows(receipt))

    return {
        "branch": branch,
        "office": office,
        "place_label": str(office) if office is not None else branch.name,
        "date_from": date_from,
        "date_to": date_to,
        "user": user,
        # «Usuarios» cuando salen todos, como en SICAV; con uno elegido, su
        # usuario, que es como lo nombra la columna.
        "users_label": user.username if user is not None else "Usuarios",
        "columns": COLUMNS,
        "rows": rows,
        "total": sum((row["amount"] for row in rows), ZERO),
    }
