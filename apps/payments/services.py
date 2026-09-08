"""
Operaciones de cobranza: emitir la deuda del mes y registrar lo que se cobra.

Las vistas no crean Charge ni Payment por su cuenta. Pasan por aquí porque
cobrar no es guardar una fila: hay que aplicar el dinero a los cargos, dejar
cada cargo en el estado que le corresponde y emitir el recibo con un
correlativo que dos cajas simultáneas no puedan repetir. Repartir eso entre
vistas haría que una sola de ellas olvidara un paso y la deuda dejara de
cuadrar.
"""

import calendar
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.services.models import Subscription

from .models import (
    Charge,
    Payment,
    PaymentAllocation,
    PaymentCommitment,
    Receipt,
    ReceiptSequence,
    ZERO,
)


# Serie única de recibos internos. No es una serie SUNAT: numera la constancia
# que se entrega en ventanilla. El día que se emitan boletas o facturas, esas
# llevarán su propia serie sin tocar esta.
DEFAULT_RECEIPT_SERIES = "R001"


def first_day_of(day):
    """El periodo al que pertenece una fecha."""
    return date(day.year, day.month, 1)


def _day_in_month(period, day):
    """`day` dentro del mes de `period`, recortado si el mes es más corto."""
    last_day = calendar.monthrange(period.year, period.month)[1]

    return date(period.year, period.month, min(day, last_day))


def monthly_due_date(policy, period, subscription):
    """Cuándo vence la mensualidad de ese periodo.

    Por mes calendario vence al cerrar el mes facturado. Por aniversario vence
    el mismo día del mes en que se instaló el servicio: es la fecha que el
    abonado tiene interiorizada, y moverla al fin de mes le cambiaría el
    compromiso sin avisarle.
    """
    if policy.billing_mode == policy.Mode.ANNIVERSARY and subscription.installation_date:
        return _day_in_month(period, subscription.installation_date.day)

    last_day = calendar.monthrange(period.year, period.month)[1]

    return date(period.year, period.month, last_day)


def build_monthly_charge(subscription, period):
    """Arma -sin guardar- la mensualidad de una suscripción para ese periodo.

    Devuelve None cuando la suscripción no debe facturarse ese mes, para que
    quien genera en lote no tenga que repetir esas condiciones.
    """
    policy = subscription.billing_policy

    if policy is None:
        return None

    if subscription.status != Subscription.Status.ACTIVE:
        return None

    amount = subscription.total_monthly_price

    if amount is None or amount <= ZERO:
        return None

    # No se factura un mes anterior a la instalación: ese servicio todavía no
    # existía y el cargo no tendría con qué justificarse.
    if subscription.installation_date:
        last_day = calendar.monthrange(period.year, period.month)[1]
        if subscription.installation_date > date(period.year, period.month, last_day):
            return None

    due_date = monthly_due_date(policy, period, subscription)
    discount_deadline = policy.discount_deadline_for(due_date)

    # Sin fecha límite no hay pronto pago que conceder: un descuento sin plazo
    # sería un descuento permanente, que es otra cosa distinta.
    early_discount = policy.discount_amount if discount_deadline else ZERO

    if early_discount >= amount:
        early_discount = ZERO
        discount_deadline = None

    last_day = calendar.monthrange(period.year, period.month)[1]

    return Charge(
        customer=subscription.customer,
        subscription=subscription,
        concept=Charge.Concept.MONTHLY,
        # El detalle es el plan, y el mes va en el periodo. El sistema
        # anterior los muestra en columnas distintas -«INTERNET 300MG» y
        # «01/09/2026 - 30/09/2026»-, asi que repetir el mes en el detalle
        # solo lo haria mas largo de leer.
        description=subscription.plan.name,
        issued_on=period,
        period=period,
        period_end=date(period.year, period.month, last_day),
        amount=amount,
        due_date=due_date,
        early_discount=early_discount,
        discount_deadline=discount_deadline,
        cut_date=policy.cut_date_for(due_date),
    )


@transaction.atomic
def generate_monthly_charges(period, branch=None, dry_run=False):
    """Emite la mensualidad de todas las suscripciones activas del periodo.

    Es idempotente: la restricción única de (suscripción, periodo) impide
    cobrar dos veces el mismo mes, así que volver a correrlo tras una caída
    completa lo que falte en vez de duplicar la deuda.
    """
    period = first_day_of(period)

    subscriptions = (
        Subscription.objects.filter(
            status=Subscription.Status.ACTIVE,
            billing_policy__isnull=False,
        )
        .select_related("customer", "plan", "billing_policy", "service_type")
    )

    if branch is not None:
        subscriptions = subscriptions.filter(address__branch=branch)

    already_charged = set(
        Charge.objects.filter(
            concept=Charge.Concept.MONTHLY,
            period=period,
            subscription__in=subscriptions,
        ).values_list("subscription_id", flat=True)
    )

    created, skipped = [], 0

    for subscription in subscriptions:
        if subscription.pk in already_charged:
            skipped += 1
            continue

        charge = build_monthly_charge(subscription, period)

        if charge is None:
            skipped += 1
            continue

        charge.full_clean()
        charge.save()
        created.append(charge)

    if dry_run:
        transaction.set_rollback(True)

    return {"period": period, "created": created, "skipped": skipped}


def outstanding_charges(customer, day=None):
    """Los cargos abiertos del abonado, del más antiguo al más reciente."""
    day = day or timezone.localdate()

    return (
        Charge.objects.filter(customer=customer)
        .outstanding()
        .select_related("subscription", "subscription__plan")
        .order_by("due_date", "pk")
    )


def customer_debt(customer, day=None):
    """Resumen de deuda del abonado tal como se muestra en pantalla."""
    day = day or timezone.localdate()
    charges = list(outstanding_charges(customer, day))

    total = sum((charge.balance_on(day) for charge in charges), ZERO)
    overdue = sum(
        (charge.balance_on(day) for charge in charges if charge.is_overdue(day)),
        ZERO,
    )

    return {
        "charges": charges,
        "count": len(charges),
        "total": total,
        "overdue_total": overdue,
        "overdue_count": sum(1 for charge in charges if charge.is_overdue(day)),
        "oldest_due_date": charges[0].due_date if charges else None,
        "as_of": day,
    }


def allocate_oldest_first(charges, amount, day=None):
    """Reparte un monto entre cargos, empezando por el que vence antes.

    Es el reparto que hace un cajero cuando el abonado entrega dinero y dice
    «a cuenta»: primero se limpia lo más viejo, que es lo que puede llevarlo
    al corte.
    """
    day = day or timezone.localdate()
    remaining = Decimal(amount)
    plan = []

    for charge in charges:
        if remaining <= ZERO:
            break

        balance = charge.balance_on(day)

        if balance <= ZERO:
            continue

        applied = balance if balance <= remaining else remaining
        plan.append((charge, applied))
        remaining -= applied

    return plan


@transaction.atomic
def next_receipt_number(series=DEFAULT_RECEIPT_SERIES):
    """Siguiente correlativo de la serie, bloqueando la fila.

    Se bloquea con select_for_update() para que dos cajas que cobran a la vez
    no se lleven el mismo número. Nunca se deduce del último recibo emitido:
    ese cálculo da el mismo resultado a dos transacciones simultáneas.
    """
    sequence, _ = ReceiptSequence.objects.get_or_create(series=series)
    sequence = ReceiptSequence.objects.select_for_update().get(pk=sequence.pk)
    sequence.last_number += 1
    sequence.save(update_fields=["last_number", "updated_at"])

    return sequence.last_number


def discount_for(charge, applied, day=None):
    """El descuento que justifica la fila del comprobante.

    Solo hay descuento cuando el abonado cancela el cargo completo dentro del
    plazo de pronto pago. Un pago parcial no lo gana: si lo ganara, pagar S/ 1
    dentro del plazo rebajaria el mes entero.
    """
    day = day or timezone.localdate()
    due = charge.amount_due_on(day)

    if due >= charge.amount:
        return ZERO

    if applied < due - charge.paid_amount:
        return ZERO

    return charge.amount - due


@transaction.atomic
def register_payment(
    *,
    customer,
    amount,
    method,
    branch,
    user,
    reference="",
    note="",
    allocations=None,
    received_at=None,
    day=None,
    series=DEFAULT_RECEIPT_SERIES,
    collector=None,
    settled=True,
    paid_at=None,
    due_date=None,
):
    """Registra un cobro, lo aplica a los cargos y emite su comprobante.

    `allocations` es una lista de (cargo, monto). Si no se pasa, el dinero se
    aplica del cargo más antiguo al más nuevo. Lo que sobre queda como saldo a
    favor en el pago -no se inventa un cargo para absorberlo.

    `settled=False` es el «Cancelado: No (Pendiente)» del comprobante: queda
    emitido pero el dinero no entro, asi que **no baja la deuda** hasta que se
    confirme con `Payment.confirm()`.
    """
    day = day or timezone.localdate()
    amount = Decimal(amount)

    if amount <= ZERO:
        raise ValidationError("El monto recibido debe ser mayor a cero.")

    if allocations is None:
        allocations = allocate_oldest_first(
            outstanding_charges(customer, day), amount, day
        )

    allocations = [(charge, Decimal(value)) for charge, value in allocations if value]

    for charge, value in allocations:
        if charge.customer_id != customer.pk:
            raise ValidationError(
                "Un pago solo puede aplicarse a cargos del mismo abonado."
            )

        if value <= ZERO:
            raise ValidationError("Los montos aplicados deben ser mayores a cero.")

        if value > charge.balance_on(day):
            raise ValidationError(
                f"No se puede aplicar S/ {value} al cargo «{charge.description}»: "
                f"su saldo es S/ {charge.balance_on(day)}."
            )

    allocated = sum((value for _, value in allocations), ZERO)

    if allocated > amount:
        raise ValidationError(
            "Lo aplicado a los cargos supera el monto recibido."
        )

    received_at = received_at or timezone.now()

    payment = Payment(
        customer=customer,
        amount=amount,
        method=method,
        reference=(reference or "").strip(),
        branch=branch,
        received_by=user,
        collector=collector,
        note=(note or "").strip(),
        received_at=received_at,
        status=(
            Payment.Status.REGISTERED if settled else Payment.Status.PENDING
        ),
        paid_at=(paid_at or received_at) if settled else None,
        due_date=due_date,
    )
    payment.full_clean(
        exclude=["received_by", "collector", "branch", "customer"]
    )
    payment.save()

    for charge, value in allocations:
        PaymentAllocation.objects.create(
            payment=payment,
            charge=charge,
            amount=value,
            discount=discount_for(charge, value, day),
        )
        charge.refresh_status(day)

    receipt = Receipt.objects.create(
        payment=payment,
        series=series,
        number=next_receipt_number(series),
        issued_at=payment.received_at,
    )

    return payment, receipt


@transaction.atomic
def create_manual_charge(
    *,
    customer,
    concept,
    description,
    amount,
    due_date,
    subscription=None,
    period=None,
    period_end=None,
    issued_on=None,
    quantity=None,
    currency="PEN",
    auto_update=False,
    early_discount=ZERO,
    discount_deadline=None,
):
    """Emite un cargo desde la ventanilla.

    El ciclo mensual sigue siendo automatico: esto no lo reemplaza ni lo
    adelanta. Se permite emitir una mensualidad a mano -el sistema anterior lo
    permite y hay casos que lo necesitan- y lo que evita duplicarla es la
    restriccion unica de (suscripcion, periodo), no que la pantalla lo
    esconda.

    Si el concepto es una mensualidad y no se indica periodo, se toma el mes
    de la fecha de emision: el formulario no pide el periodo aparte porque la
    fecha ya lo dice.
    """
    issued_on = issued_on or timezone.localdate()

    if concept == Charge.Concept.MONTHLY and period is None:
        period = first_day_of(issued_on)

    if period and period_end is None:
        last_day = calendar.monthrange(period.year, period.month)[1]
        period_end = date(period.year, period.month, last_day)

    charge = Charge(
        customer=customer,
        subscription=subscription,
        concept=concept,
        description=description,
        issued_on=issued_on,
        quantity=Decimal(quantity) if quantity is not None else Decimal("1.00000"),
        currency=currency,
        auto_update=auto_update,
        amount=Decimal(amount),
        due_date=due_date,
        period=period,
        period_end=period_end,
        early_discount=Decimal(early_discount or ZERO),
        discount_deadline=discount_deadline,
    )
    charge.full_clean()
    charge.save()

    return charge


@transaction.atomic
def grant_commitment(
    *,
    customer,
    charges,
    committed_date,
    reason,
    user,
    amount=None,
    day=None,
    authorized_by=None,
):
    """Concede un compromiso de pago sobre cargos concretos.

    No mueve saldo: el abonado sigue debiendo lo mismo. Lo que cambia es que
    esos cargos dejan de empujarlo al corte hasta la fecha prometida.

    El monto, si no se indica, es el saldo de los cargos elegidos. Se permite
    indicarlo aparte porque el abonado puede comprometerse por menos de lo que
    debe, y ese acuerdo hay que poder registrarlo tal como se hizo.
    """
    day = day or timezone.localdate()
    charges = list(charges)

    if not charges:
        raise ValidationError(
            "Seleccione al menos un cargo: el compromiso protege cargos "
            "concretos, no la deuda futura."
        )

    for charge in charges:
        if charge.customer_id != customer.pk:
            raise ValidationError(
                "Un compromiso solo puede cubrir cargos del mismo abonado."
            )

        if charge.status not in (
            Charge.Status.PENDING,
            Charge.Status.PARTIALLY_PAID,
        ):
            raise ValidationError(
                f"El cargo «{charge.description}» ya no tiene saldo pendiente."
            )

    if committed_date < day:
        raise ValidationError(
            "La fecha del compromiso debe ser futura: un plazo ya vencido no "
            "aplaza ningún corte."
        )

    outstanding = sum((charge.balance_on(day) for charge in charges), ZERO)
    amount = Decimal(amount) if amount is not None else outstanding

    if amount <= ZERO:
        raise ValidationError("El monto comprometido debe ser mayor a cero.")

    if amount > outstanding:
        raise ValidationError(
            f"El compromiso (S/ {amount}) supera el saldo de los cargos "
            f"elegidos (S/ {outstanding})."
        )

    commitment = PaymentCommitment(
        customer=customer,
        amount=amount,
        committed_date=committed_date,
        reason=(reason or "").strip(),
        granted_by=user,
        authorized_by=authorized_by,
    )
    commitment.full_clean(
        exclude=["granted_by", "authorized_by", "customer"]
    )
    commitment.save()
    commitment.charges.set(charges)

    return commitment


def customer_commitments(customer):
    """Compromisos del abonado, reevaluados contra el calendario de hoy.

    Se reevalúan al leerlos porque un compromiso se rompe por el paso del
    tiempo, no por una acción de nadie: sin esto, uno vencido seguiría
    figurando como vigente hasta que alguien lo tocara.
    """
    commitments = (
        PaymentCommitment.objects.filter(customer=customer)
        .select_related("granted_by")
        .prefetch_related("charges")
    )

    for commitment in commitments:
        commitment.evaluate()

    return commitments


def receipt_series_options():
    """Las series de comprobante disponibles para cobrar.

    Salen de las filas de ReceiptSequence, que es donde vive el correlativo:
    ofrecer una serie que no tiene fila obligaria a crearla al vuelo dentro
    del cobro, y el numero se emitiria sin el bloqueo que evita repetirlo.
    La serie por defecto se asegura para que la ventanilla nunca quede sin
    ninguna opcion.
    """
    ReceiptSequence.objects.get_or_create(series=DEFAULT_RECEIPT_SERIES)

    return list(ReceiptSequence.objects.order_by("series"))


def collector_options():
    """Los usuarios que pueden figurar como cobrador.

    Son los del rol de ventas: el cobrador es quien trajo el dinero, y en el
    flujo real es el vendedor que cobro en campo. No se ofrece cualquier
    usuario para que el cuadre por cobrador signifique algo.
    """
    User = get_user_model()

    return User.objects.filter(
        role=User.Role.SALES,
        is_active=True,
    ).order_by("first_name", "last_name", "username")


def authorizer_options():
    """Quien puede autorizar un compromiso de pago.

    Aplazar el corte de un abonado que ya debe es una decision comercial, asi
    que se ofrecen los perfiles que responden por ella -supervision,
    retenciones y administracion- y no la ventanilla que la teclea.
    """
    User = get_user_model()

    return User.objects.filter(
        role__in=(
            User.Role.SUPERVISOR,
            User.Role.RETENTION,
            User.Role.ADMIN,
        ),
        is_active=True,
    ).order_by("first_name", "last_name", "username")
