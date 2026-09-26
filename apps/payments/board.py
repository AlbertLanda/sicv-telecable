"""
Las filas del tablero de deuda del abonado.

La tabla junta dos cosas que el operador lee a la vez: los cargos que el
abonado debe y lo que una orden dejó por cobrar sin que nadie lo haya resuelto
todavía -una deuda propuesta, la diferencia de un traslado-. Lo segundo iba en
tarjetas encima de la tabla; con varias acumuladas empujaban la primera deuda
por debajo del pliegue y había que leer la cuenta en dos sitios.

Lo pendiente sigue sin ser deuda: no suma al saldo y no se puede marcar para
cobrar. Por eso cada fila dice qué es, y la plantilla pinta lo que recibe sin
tener que deducirlo.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.template.defaultfilters import date as format_date
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import number_format

from .models import Charge, ProposedCharge
from .proposals import suggested_proposed_charge_amount
from .services import active_subscription


#: Cómo se escriben las fechas en la tabla: «14 Sep 2026». El mes en letras se
#: lee sin pensar; «14/09/2026» obliga a traducir el 09 y, en una columna de
#: fechas iguales, se confunde con la de al lado.
DATE_FORMAT = "j M Y"


@dataclass
class DebtRow:
    """Una fila del tablero, ya decidida.

    `detail` es el nombre corto que se lee en la columna; `full_detail`, todo
    lo demás -la descripción entera, la orden, el desglose-, que va en el
    rótulo emergente para no cargar la fila.

    `charge` solo lo llevan las filas que se pueden marcar. `status_url` es a
    dónde lleva el estado: el compromiso que protege el cargo, la orden que lo
    originó o, si está pendiente y el operador puede resolverlo, la pantalla
    donde se resuelve. `status_action` dice eso mismo en palabras.
    """

    kind: str
    date: date
    detail: str
    full_detail: str
    status: str
    tone: str
    status_title: str = ""
    status_url: str = ""
    status_action: str = ""
    period: str = ""
    due_date: date | None = None
    amount: Decimal | None = None
    charge: Charge | None = None
    order_number: str = ""

    @property
    def is_pending(self):
        return self.charge is None


# ---------- El detalle en dos palabras ----------
#
# La descripción de un cargo puede ser larga -«AVERÍA INTERNET - RESPONSABILIDAD
# DEL CLIENTE»- o no decir lo que es: la de una mensualidad es el nombre del
# plan. En la columna va lo que se pregunta en ventanilla, «¿qué es esto?», y
# eso cabe en dos palabras. Lo demás sigue a un pase del cursor.

#: Palabras que no dicen nada cuando solo caben dos.
FILLER = frozenset({
    "a", "al", "con", "de", "del", "e", "el", "en", "la", "las", "los",
    "para", "por", "y",
})

#: Siglas y marcas que se leen en mayúsculas aunque el resto no.
UPPERCASE = frozenset({"APP", "DUO", "FTTH", "HD", "IPTV", "ONU", "TV"})


def _word(word, first):
    if word.upper() in UPPERCASE or any(char.isdigit() for char in word):
        return word.upper()

    word = word.lower()
    return word[:1].upper() + word[1:] if first else word


def short_detail(text, words=2):
    """«AVERÍA INTERNET - RESPONSABILIDAD DEL CLIENTE» → «Avería internet».

    Lo que va tras un guion suelto o entre paréntesis es una precisión de la
    descripción, no su nombre, y se cae. El doble guion del catálogo
    -«PUBLICIDAD -- BANNER»- separa familia y concepto, y los dos cuentan.
    """
    head = re.split(r"\s+-\s+|\s*\(", text or "", maxsplit=1)[0]
    kept = [
        word for word in re.findall(r"[\w/.]+", head)
        if word.lower() not in FILLER
    ][:words]

    return " ".join(_word(word, index == 0) for index, word in enumerate(kept))


def plan_name(name):
    """«PLAN INTERNET ESTANDAR 600MG - 2026» → «Plan internet estandar 600MG - 2026».

    Es un nombre del catálogo y va entero: el plan es lo que distingue una
    mensualidad de otra. Solo se reescribe el que viene todo en mayúsculas,
    como los demás detalles; uno escrito con cuidado -«Internet 1000 Mbps»-
    se deja como está, que pasarlo a minúsculas deformaría sus unidades.
    """
    if name != name.upper():
        return name

    return " ".join(_word(word, index == 0) for index, word in enumerate(name.split(" ")))


def charge_detail(charge, active_plan=None):
    """El nombre corto del cargo. `active_plan` es el plan de la suscripción
    activa del abonado, para las mensualidades puestas a mano."""
    if charge.concept == Charge.Concept.MONTHLY:
        # Una mensualidad automática se nombra por el plan contratado: es lo
        # que el abonado paga y lo que pregunta en ventanilla. «Automática» es
        # la que sigue al plan -la casilla «Actualizar automáticamente»-, y lo
        # son todas las del ciclo mensual.
        #
        # La del ciclo va atada a su suscripción y guarda en la descripción el
        # plan del mes facturado, que sigue siendo el correcto aunque después
        # se cambie de plan. La puesta a mano no tiene suscripción: su plan es
        # el de la suscripción activa, el mismo que le dio el monto.
        if charge.auto_update:
            if charge.concept_item_id is None and charge.subscription_id:
                return plan_name(charge.description or charge.subscription.plan.name)
            if active_plan is not None:
                return plan_name(active_plan.name)

        # Fija -un monto pactado que no sigue al plan- o sin plan al que
        # atarla: dice lo que es.
        return "Mensualidad"

    return short_detail(charge.description) or charge.get_concept_display()


def charge_period(charge):
    """«Sep 2026» si cubre un mes calendario; si no, «15 Sep – 14 Oct 2026».

    El mismo idioma que las fechas de la tabla. «01/09/2026 - 30/09/2026»
    ocupaba el doble para decir un mes.
    """
    start, end = charge.period, charge.period_end

    if not start:
        return ""
    if not end:
        return format_date(start, DATE_FORMAT)

    last_day = calendar.monthrange(start.year, start.month)[1]
    if start.day == 1 and end == start.replace(day=last_day):
        return format_date(start, "M Y")

    if start.year == end.year:
        return f"{format_date(start, 'j M')} – {format_date(end, DATE_FORMAT)}"

    return f"{format_date(start, DATE_FORMAT)} – {format_date(end, DATE_FORMAT)}"


def _active_plan(customer, charges):
    """El plan del abonado, una sola vez y solo si alguna mensualidad puesta a
    mano lo necesita para nombrarse."""
    needs_plan = any(
        charge.concept == Charge.Concept.MONTHLY
        and charge.auto_update
        and not charge.subscription_id
        for charge in charges
    )
    active = active_subscription(customer) if needs_plan else None

    return active.plan if active else None


@dataclass
class ChargeLine:
    """Un cargo marcado, tal como lo repite la pantalla de cobro."""

    charge: Charge
    detail: str
    period: str


def charge_lines(customer, charges):
    """Los cargos con el mismo nombre y periodo que tenían en el tablero.

    El cajero reconoce en el cobro las filas que acaba de marcar. Con otro
    nombre -la descripción larga del catálogo- tendría que volver a
    compararlas una por una con las del tablero.
    """
    active_plan = _active_plan(customer, charges)

    return [
        ChargeLine(
            charge=charge,
            detail=charge_detail(charge, active_plan),
            period=charge_period(charge),
        )
        for charge in charges
    ]


# ---------- Las filas ----------

def _money(value):
    return f"S/ {number_format(value, 2)}"


def debt_rows(
    *,
    customer,
    charges,
    proposals,
    transfers,
    commitments,
    can_view_order,
    can_resolve_proposal,
    can_resolve_transfer,
    day=None,
):
    """Lo pendiente primero -espera una decisión- y después los cargos, en el
    orden en que vencen."""
    day = day or timezone.localdate()

    def order_url(order):
        return reverse("work_orders:detail", args=[order.pk]) if can_view_order else ""

    rows = []

    for proposal in proposals:
        order = proposal.work_order
        url, action = "", ""

        if can_resolve_proposal:
            url = reverse(
                "payments:proposal_resolve",
                kwargs={"pk": customer.pk, "proposal_pk": proposal.pk},
            )
            action = f"Resolver la deuda de {order.order_number}"
        elif can_view_order:
            url, action = order_url(order), f"Abrir {order.order_number}"

        rows.append(DebtRow(
            kind="proposal",
            date=timezone.localdate(proposal.created_at),
            detail=proposal.display_title,
            full_detail=f"{proposal.description} · {order.order_number}",
            status="Pendiente",
            tone="warning",
            status_title=(
                "Todavía no es deuda: falta aceptarla con su monto o "
                "descartarla."
            ),
            status_url=url,
            status_action=action,
            amount=suggested_proposed_charge_amount(proposal),
            order_number=order.order_number,
        ))

    for transfer in transfers:
        order = transfer.work_order
        url, action = "", ""

        if can_resolve_transfer:
            url = reverse(
                "payments:transfer_reconciliation_resolve",
                kwargs={"pk": customer.pk, "transfer_pk": transfer.pk},
            )
            action = f"Regularizar el traslado {order.order_number}"
        elif can_view_order:
            url, action = order_url(order), f"Abrir {order.order_number}"

        # La cuenta completa va en el rótulo emergente: en la fila solo el
        # nombre, y la diferencia en la columna del monto.
        figures = [f"Diferencia {_money(transfer.reconciliation_difference)}"]
        if transfer.actual_total is not None:
            figures.append(f"Real {_money(transfer.actual_total)}")
        if transfer.customer_agreed_amount is not None:
            figures.append(f"Acordado {_money(transfer.customer_agreed_amount)}")

        rows.append(DebtRow(
            kind="transfer",
            date=timezone.localdate(transfer.updated_at),
            detail="Regularización traslado",
            full_detail=(
                f"Regularización de traslado {order.order_number} · "
                + " · ".join(figures)
            ),
            status="Pendiente",
            tone="warning",
            status_title=(
                "El costo real del traslado no coincide con lo cobrado: falta "
                "decidir qué se hace con la diferencia."
            ),
            status_url=url,
            status_action=action,
            amount=transfer.reconciliation_difference,
            order_number=order.order_number,
        ))

    # El compromiso que protege cada cargo, sin una consulta por fila: los
    # compromisos llegan con sus cargos precargados. Si dos cubren el mismo
    # cargo manda el que vence antes, como en `Charge.active_commitment`.
    commitment_of = {}
    for commitment in sorted(commitments, key=lambda c: c.committed_date):
        for charge in commitment.charges.all():
            commitment_of.setdefault(charge.pk, commitment)

    # La orden de la que nació cada cargo, si nació de una. Una sola consulta
    # para toda la tabla.
    origin_of = {
        proposal.charge_id: proposal.work_order
        for proposal in ProposedCharge.objects.filter(
            charge__in=[charge.pk for charge in charges]
        ).select_related("work_order")
    } if charges else {}

    active_plan = _active_plan(customer, charges)

    for charge in charges:
        rows.append(_charge_row(
            charge,
            customer=customer,
            commitment=commitment_of.get(charge.pk),
            origin=origin_of.get(charge.pk),
            order_url=order_url,
            active_plan=active_plan,
            day=day,
        ))

    return rows


def _charge_row(charge, *, customer, commitment, origin, order_url, active_plan, day):
    # Tres estados y en este orden: lo que cambia qué se le puede decir al
    # abonado va antes. Un cargo comprometido no empuja al corte aunque esté
    # vencido, y eso es lo que el operador necesita saber de él. El pago
    # parcial no es un estado más: sigue pendiente o vencido, y lo que ya se
    # pagó va en el rótulo emergente.
    partial = ""
    if charge.status == Charge.Status.PARTIALLY_PAID:
        partial = (
            f" · Pago parcial: {_money(charge.paid_amount)} de "
            f"{_money(charge.amount)}"
        )

    # El estado lleva a lo que lo explica: al compromiso si lo hay, y si no a
    # la orden de la que nació el cargo. Un cargo sin ninguno de los dos
    # -una mensualidad, un cargo puesto a mano- no tiene a dónde llevar.
    url = order_url(origin) if origin else ""
    action = f"Abrir {origin.order_number}" if url else ""

    if commitment:
        # Morado y no ámbar: un compromiso ya es un acuerdo, no algo abierto,
        # y en el mismo color que «Pendiente» había que leer la etiqueta para
        # distinguirlos.
        status, tone = "Compromiso", "violet"
        status_title = (
            f"Compromiso de pago {commitment.pk}: paga el "
            f"{format_date(commitment.committed_date, DATE_FORMAT)}"
        )
        url = reverse(
            "payments:commitment_detail",
            kwargs={"pk": customer.pk, "commitment_pk": commitment.pk},
        )
        action = f"Ver el compromiso {commitment.pk}"
    elif charge.is_overdue(day):
        status, tone = "Vencido", "danger"
        status_title = (
            f"Venció el {format_date(charge.due_date, DATE_FORMAT)}{partial}"
        )
    else:
        status, tone = "Pendiente", "warning"
        status_title = (
            f"Vence el {format_date(charge.due_date, DATE_FORMAT)}{partial}"
        )

    full_detail = [charge.description]
    if origin:
        full_detail.append(origin.order_number)
    full_detail += [
        f"{component.get_kind_display()}: {component.description} "
        f"{_money(component.amount)}"
        for component in charge.components.all()
    ]

    return DebtRow(
        kind="charge",
        date=charge.issued_on,
        detail=charge_detail(charge, active_plan),
        full_detail=" · ".join(full_detail),
        period=charge_period(charge),
        due_date=charge.due_date,
        status=status,
        tone=tone,
        status_title=status_title,
        status_url=url,
        status_action=action,
        amount=charge.amount,
        charge=charge,
        order_number=origin.order_number if origin else "",
    )
