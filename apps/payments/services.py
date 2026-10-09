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
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.services.models import Subscription
from apps.customers.models import Customer

from .models import (
    Charge,
    ChargeComponent,
    ChargeConcept,
    Payment,
    PaymentAllocation,
    PaymentOperationEvent,
    PaymentCommitment,
    PaymentCommitmentInstallment,
    Receipt,
    ReceiptSequence,
    ZERO,
    format_receipt_number,
)


def paid_between(date_from, date_to, prefix=""):
    """Los pagos cuyo día de cobro cae en el rango, como condición `Q`.

    El día de cobro es la fecha real de pago y, si el pago todavía no la
    tiene -un «Cancelado: No»-, la fecha en que se registró. Es la regla de la
    caja del día; vive aquí para que cualquier otra consulta por día de cobro
    cuente el mismo día que la caja para el mismo pago.

    `prefix` permite aplicarla desde otra tabla: `"payment__"` para filtrar
    comprobantes por el día de su pago. Las dos fechas son inclusivas y se
    leen en la hora de Lima.
    """
    return Q(**{
        f"{prefix}paid_at__date__gte": date_from,
        f"{prefix}paid_at__date__lte": date_to,
    }) | Q(**{
        f"{prefix}paid_at__isnull": True,
        f"{prefix}received_at__date__gte": date_from,
        f"{prefix}received_at__date__lte": date_to,
    })


# Serie única de recibos internos. No es una serie SUNAT: numera la constancia
# que se entrega en ventanilla. El día que se emitan boletas o facturas, esas
# llevarán su propia serie sin tocar esta.
DEFAULT_RECEIPT_SERIES = "R001"


@transaction.atomic
def ensure_reconnection_charge(order):
    """Una deuda fija por corte de morosidad ejecutado, nunca por mero atraso."""
    if (order.order_type.code != "CUT" or not order.result
            or order.result.code != "SUCCESSFUL" or not order.reason
            or order.reason.code not in {"DELINQUENCY", "NON_PAYMENT"}):
        return None
    Customer.objects.select_for_update().get(pk=order.subscription.customer_id)
    subscription = Subscription.objects.select_for_update(of=("self",)).select_related("billing_policy").get(pk=order.subscription_id)
    if subscription.status != Subscription.Status.SUSPENDED or subscription.cut_date is None:
        return None
    amount = subscription.billing_policy.reconnection_fee if subscription.billing_policy else Decimal("15.00")
    if amount <= ZERO:
        return None
    today = timezone.localdate()
    charge, created = Charge.objects.get_or_create(
        source_cut_order=order,
        defaults={
            "customer": subscription.customer, "subscription": subscription,
            "concept": Charge.Concept.OTHER,
            "concept_item": ChargeConcept.objects.filter(code="reconexion", is_active=True).first(),
            "description": f"Reconexión por corte de morosidad · {order.order_number}",
            "amount": amount, "due_date": today, "issued_on": today,
            "auto_update": False,
        },
    )
    if created:
        charge.full_clean()
    return charge


def first_day_of(day):
    """El periodo al que pertenece una fecha."""
    return date(day.year, day.month, 1)


def _day_in_month(period, day):
    """`day` dentro del mes de `period`, recortado si el mes es más corto."""
    last_day = calendar.monthrange(period.year, period.month)[1]

    return date(period.year, period.month, min(day, last_day))


def monthly_coverage(policy, period, subscription):
    """Mes de referencia estable y fechas efectivas del ciclo contratado."""
    period = first_day_of(period)
    if policy.billing_mode == policy.Mode.ANNIVERSARY:
        anchor = subscription.billing_cycle or (
            subscription.installation_date.day if subscription.installation_date else None
        )
        if not anchor or not 1 <= anchor <= 31:
            raise ValidationError("El servicio por aniversario requiere un ciclo entre 1 y 31.")
        next_month = first_day_of(period + timedelta(days=32))
        start = _day_in_month(period, anchor)
        end = _day_in_month(next_month, anchor) - timedelta(days=1)
    else:
        start = period
        end = date(period.year, period.month, calendar.monthrange(period.year, period.month)[1])
    if subscription.installation_date and start < subscription.installation_date <= end:
        start = subscription.installation_date
    return start, end


def monthly_due_date(policy, period, subscription):
    """La mensualidad vence el último día que cubre: 14/09–13/10 vence 13/10."""
    return monthly_coverage(policy, period, subscription)[1]


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

    if (policy.billing_mode == policy.Mode.ANNIVERSARY
            and not subscription.billing_cycle and not subscription.installation_date):
        return None
    coverage_start, coverage_end = monthly_coverage(policy, period, subscription)
    if policy.billing_mode == policy.Mode.CALENDAR_MONTH and coverage_start > period:
        amount = prorated_amount(amount, (coverage_end - coverage_start).days + 1)

    due_date = monthly_due_date(policy, period, subscription)
    discount_deadline = policy.discount_deadline_for(due_date)

    # Sin fecha límite no hay pronto pago que conceder: un descuento sin plazo
    # sería un descuento permanente, que es otra cosa distinta.
    early_discount = policy.discount_amount if discount_deadline else ZERO

    if early_discount >= amount:
        early_discount = ZERO
        discount_deadline = None

    return Charge(
        customer=subscription.customer,
        subscription=subscription,
        concept=Charge.Concept.MONTHLY,
        # El detalle es el plan, y el mes va en el periodo. El sistema
        # anterior los muestra en columnas distintas -«INTERNET 300MG» y
        # «01/09/2026 - 30/09/2026»-, asi que repetir el mes en el detalle
        # solo lo haria mas largo de leer.
        description=subscription.plan.name,
        issued_on=coverage_start,
        period=period,
        period_start=coverage_start,
        period_end=coverage_end,
        amount=amount,
        due_date=due_date,
        early_discount=early_discount,
        discount_deadline=discount_deadline,
        cut_date=policy.cut_date_for(due_date),
    )


def snapshot_monthly_charge_components(charge):
    """Congela el desglose del paquete sin cambiar el monto del cargo."""
    if charge.concept != Charge.Concept.MONTHLY or charge.subscription_id is None:
        return []

    if charge.components.exists():
        return list(charge.components.all())

    subscription = charge.subscription
    app_amount = Decimal(
        subscription.included_app_component_amount or ZERO
    )

    components = []

    if (
        subscription.included_app_plan_id
        and app_amount > ZERO
        and app_amount < charge.amount
    ):
        main_amount = charge.amount - app_amount

        components.append(
            ChargeComponent(
                charge=charge,
                kind=ChargeComponent.Kind.MAIN,
                code=subscription.service_type.code,
                description=subscription.plan.name,
                amount=main_amount,
            )
        )
        components.append(
            ChargeComponent(
                charge=charge,
                kind=ChargeComponent.Kind.INCLUDED_APP,
                code="APPS",
                description=subscription.included_app_plan.name,
                amount=app_amount,
            )
        )
    else:
        components.append(
            ChargeComponent(
                charge=charge,
                kind=ChargeComponent.Kind.MAIN,
                code=subscription.service_type.code,
                description=subscription.plan.name,
                amount=charge.amount,
            )
        )

    ChargeComponent.objects.bulk_create(components)
    return components


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
        subscriptions = subscriptions.filter(
            Q(address__zone__branch=branch)
            | Q(address__zone__isnull=True, address__customer__branch=branch)
        )

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
        snapshot_monthly_charge_components(charge)
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
        .prefetch_related("components")
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


def receipt_sequence(code=DEFAULT_RECEIPT_SERIES):
    """El talonario que responde a ese código, creándolo si no existe.

    Se busca por `code` y no por la serie impresa porque la serie se repite:
    «S010» nombra tres blocks distintos, y elegir por ella devolvería
    cualquiera de los tres.

    El que se crea aquí nace retirado. Llegar a este punto significa que
    nadie eligió ese talonario en la ventanilla -es el de respaldo, o un
    código que no está en el padrón-, y ofrecerlo después en el desplegable
    pondría a elegir un block que no existe en papel.
    """
    sequence, _ = ReceiptSequence.objects.get_or_create(
        code=code,
        defaults={"series": code, "label": code, "is_active": False},
    )

    return sequence


@transaction.atomic
def next_receipt_number(sequence=DEFAULT_RECEIPT_SERIES):
    """Siguiente correlativo del talonario, bloqueando su fila.

    Se bloquea con select_for_update() para que dos cajas que cobran a la vez
    no se lleven el mismo número. Nunca se deduce del último recibo emitido:
    ese cálculo da el mismo resultado a dos transacciones simultáneas.

    Acepta el talonario o su código: casi todas las llamadas traen el objeto,
    pero la firma antigua pasaba una cadena y sigue valiendo.
    """
    if not isinstance(sequence, ReceiptSequence):
        sequence = receipt_sequence(sequence)

    sequence = ReceiptSequence.objects.select_for_update().get(pk=sequence.pk)
    sequence.last_number += 1
    sequence.save(update_fields=["last_number", "updated_at"])

    return sequence.last_number


@transaction.atomic
def issue_receipt_number(sequence, number=None):
    """El número que se imprime, venga del correlativo o del operador.

    El campo es editable en pantalla -hay blocks de papel que ya vienen
    numerados y hay que escribir el número que toca-, así que el escrito
    manda sobre el propuesto.

    Cuando el operador escribe uno en un talonario que sí numera solo, el
    correlativo se adelanta hasta ahí: si se salta del 300 al 350, el
    siguiente cobro sale 351 y no vuelve a repetir los que quedaron en medio.
    """
    if number is None:
        if not sequence.autonumber:
            raise ValidationError(
                f"El talonario «{sequence.label}» no numera solo: escriba el "
                f"número del comprobante."
            )

        return next_receipt_number(sequence)

    number = int(number)

    if number <= 0:
        raise ValidationError("El número del comprobante debe ser mayor a cero.")

    bloqueado = ReceiptSequence.objects.select_for_update().get(pk=sequence.pk)

    if Receipt.objects.filter(sequence=bloqueado, number=number).exists():
        raise ValidationError(
            f"El comprobante {sequence.series}-"
            f"{format_receipt_number(number)} ya fue emitido."
        )

    if bloqueado.autonumber and number > bloqueado.last_number:
        bloqueado.last_number = number
        bloqueado.save(update_fields=["last_number", "updated_at"])

    return number


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


def payment_money(value):
    """Importe finito y representable sin redondear dinero del operador."""
    try:
        amount = Decimal(value)
        if (not amount.is_finite() or abs(amount) > Decimal("9999999999.99")
                or amount != amount.quantize(Decimal("0.01"))):
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Indique un importe válido con hasta dos decimales.")
    return amount


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
    number=None,
    office=None,
    collector=None,
    settled=True,
    paid_at=None,
    due_date=None,
    full_monthly_only=False,
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
    amount = payment_money(amount)

    if amount <= ZERO:
        raise ValidationError("El monto recibido debe ser mayor a cero.")

    # Todos los cambios de aplicaciones para un abonado toman este bloqueo
    # antes de leer saldos. Es compartido por registro, confirmación y anulación.
    Customer.objects.select_for_update().get(pk=customer.pk)

    if allocations is None:
        allocations = allocate_oldest_first(
            Charge.objects.select_for_update().filter(customer=customer).outstanding().order_by("due_date", "pk"),
            amount, day,
        )

    allocations = [(charge, payment_money(value)) for charge, value in allocations if value]

    ids = [charge.pk for charge, value in allocations]
    if len(ids) != len(set(ids)):
        raise ValidationError("Un cargo no puede repetirse en el mismo cobro.")
    fresh = {charge.pk: charge for charge in Charge.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if len(fresh) != len(ids):
        raise ValidationError("Uno de los cargos ya no existe. Actualice el tablero.")
    allocations = [(fresh[charge.pk], value) for charge, value in allocations]

    for charge, value in allocations:
        if charge.customer_id != customer.pk:
            raise ValidationError(
                "Un pago solo puede aplicarse a cargos del mismo abonado."
            )

        if value <= ZERO:
            raise ValidationError("Los montos aplicados deben ser mayores a cero.")

        if charge.status == Charge.Status.CANCELLED:
            raise ValidationError("No se puede cobrar un cargo anulado.")

        if value > charge.balance_on(day):
            raise ValidationError(
                f"No se puede aplicar S/ {value} al cargo «{charge.description}»: "
                f"su saldo es S/ {charge.balance_on(day)}."
            )
        if full_monthly_only and charge.concept == Charge.Concept.MONTHLY and value != charge.balance_on(day):
            raise ValidationError(
                f"La mensualidad «{charge.description}» se paga completa: "
                f"debe aplicar S/ {charge.balance_on(day):.2f}. Seleccione los periodos que desea cobrar."
            )

    allocated = sum((value for _, value in allocations), ZERO)

    if allocated > amount:
        raise ValidationError(
            "Lo aplicado a los cargos supera el monto recibido."
        )

    received_at = received_at or timezone.now()

    # El talonario se resuelve antes de tocar nada: si la serie elegida no
    # numera sola y no vino número, el cobro no debe llegar a escribirse.
    sequence = series
    if not isinstance(sequence, ReceiptSequence):
        sequence = receipt_sequence(sequence)

    if number is None and not sequence.autonumber:
        raise ValidationError(
            f"El talonario «{sequence.label}» no numera solo: escriba el "
            f"número del comprobante."
        )

    from .cash import lock_payment_session, book_payment
    cash_session = lock_payment_session(
        office=office, cashier=user, paid_at=paid_at or received_at,
    ) if settled else None

    payment = Payment(
        customer=customer,
        amount=amount,
        method=method,
        reference=(reference or "").strip(),
        branch=branch,
        office=office,
        received_by=user,
        collector=collector,
        note=(note or "").strip(),
        received_at=received_at,
        status=(
            Payment.Status.REGISTERED if settled else Payment.Status.PENDING
        ),
        paid_at=(paid_at or received_at) if settled else None,
        due_date=due_date,
        full_monthly_only=full_monthly_only,
    )
    payment.full_clean(
        exclude=["received_by", "collector", "branch", "office", "customer"]
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
        sequence=sequence,
        series=sequence.series,
        number=issue_receipt_number(sequence, number),
        issued_at=payment.received_at,
    )

    book_payment(payment, cash_session, user)

    PaymentOperationEvent.objects.create(
        payment=payment, actor=user,
        action=(PaymentOperationEvent.Action.REGISTERED if settled else PaymentOperationEvent.Action.PENDING),
    )

    return payment, receipt


# El mes comercial de la cobranza. Con los dias reales del calendario, el
# mismo corte de cinco dias costaria distinto en febrero que en marzo, y el
# abonado que reclama por que su prorrateo cambio tendria razon.
BILLING_MONTH_DAYS = 30


# El concepto con el que abre la pantalla de nueva deuda. Se busca por codigo
# y no por nombre: el nombre se puede corregir desde el admin -una tilde, una
# mayuscula- y la pantalla dejaria de encontrarlo.
DEFAULT_CONCEPT_CODE = "mensualidad"


def default_concept():
    """El concepto con el que abre la ventanilla, o el primero que haya.

    Sin catalogo sembrado devuelve None y el desplegable sale vacio, que es
    mejor que reventar la pantalla: lo que falta es un dato, no el codigo.
    """
    catalog = ChargeConcept.objects.filter(is_active=True)

    return (
        catalog.filter(code=DEFAULT_CONCEPT_CODE).first()
        or catalog.first()
    )


def active_subscription(customer):
    """La suscripción activa que representa al abonado en cobranza.

    La primera activa, por orden de alta. Es la que da la mensualidad de
    referencia y el plan que se nombra en una mensualidad puesta a mano: las
    dos preguntas tienen que mirar la misma suscripción, o el monto diría un
    plan y el detalle otro.
    """
    return (
        customer.subscriptions.filter(status=Subscription.Status.ACTIVE)
        .select_related("plan")
        .order_by("pk")
        .first()
    )


def monthly_reference(customer):
    """Mensualidad del abonado, la base de todo prorrateo.

    Sale de su suscripcion activa: es la cifra que el operador tiene delante
    al emitir una mensualidad a mano y la que reparte el mes en dias. Sin
    suscripcion activa devuelve cero, y la pantalla lo dice en vez de
    calcular sobre esa nada.
    """
    active = active_subscription(customer)

    return active.total_monthly_price if active else ZERO


def daily_rate(monthly):
    """Lo que vale un dia de servicio sobre una mensualidad dada."""
    monthly = Decimal(monthly or ZERO)

    if monthly <= ZERO:
        return ZERO

    return (monthly / BILLING_MONTH_DAYS).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def prorated_amount(monthly, days):
    """Cuanto se cobra por `days` dias de una mensualidad.

    Se multiplica el valor del dia ya redondeado, y no la mensualidad partida
    en crudo, porque es la cifra que el operador ve en pantalla: si dice
    «S/ 2.63 por dia», diez dias tienen que dar 26.30 y no 26.3333 recortado
    aparte.

    El mes entero es la excepcion: vale la mensualidad y no la suma de sus
    treinta dias. Con 79.00, el dia redondeado es 2.63 y treinta de esos dan
    78.90, diez centimos menos que el mes que el abonado tiene contratado. El
    redondeo puede repartir un periodo partido; no puede rebajar el plan.
    """
    rate = daily_rate(monthly)

    if rate <= ZERO or not days or days <= 0:
        return ZERO

    if days >= BILLING_MONTH_DAYS:
        return Decimal(monthly).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    return (rate * Decimal(days)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


@transaction.atomic
def create_manual_charge(
    *,
    customer,
    concept,
    description,
    amount,
    due_date,
    concept_item=None,
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

    `concept` es la familia -como se comporta la deuda- y `concept_item` el
    concepto exacto del catalogo que eligio el operador. El ciclo mensual solo
    pasa la primera: emite desde el plan contratado, sin pasar por el catalogo
    de ventanilla.
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
        concept_item=concept_item,
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
    user,
    reason="",
    amount=None,
    day=None,
    authorized_by=None,
    installments=None,
    representative="",
    representative_document="",
):
    """Concede un compromiso de pago sobre cargos concretos.

    No mueve saldo: el abonado sigue debiendo lo mismo. Lo que cambia es que
    esos cargos dejan de empujarlo al corte hasta la fecha prometida.

    El monto, si no se indica, es el saldo de los cargos elegidos. Se permite
    indicarlo aparte porque el abonado puede comprometerse por menos de lo que
    debe, y ese acuerdo hay que poder registrarlo tal como se hizo.

    `installments` es el plan de cuotas -pares (numero, monto, fecha)- con el
    que el abonado piensa pagarlo. Es detalle del acuerdo y no otra promesa:
    la fecha que aplaza el corte sigue siendo `committed_date`, una sola. Si
    cada cuota protegiera hasta la siguiente, la proteccion se renovaria sola y
    un plan de quince cuotas dejaria al abonado fuera del corte durante meses
    sin que nadie lo volviera a decidir.
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

    cuotas = _clean_installments(installments, amount)

    commitment = PaymentCommitment(
        customer=customer,
        amount=amount,
        committed_date=committed_date,
        reason=(reason or "").strip(),
        representative=(representative or "").strip(),
        representative_document=(representative_document or "").strip(),
        granted_by=user,
        authorized_by=authorized_by,
    )
    commitment.full_clean(
        exclude=["granted_by", "authorized_by", "customer"]
    )
    commitment.save()
    commitment.charges.set(charges)

    for numero, monto, fecha in cuotas:
        PaymentCommitmentInstallment.objects.create(
            commitment=commitment,
            number=numero,
            amount=monto,
            due_date=fecha,
        )

    return commitment


def _clean_installments(installments, amount):
    """Valida el plan de cuotas contra lo que se esta comprometiendo.

    Dos reglas, y las dos por el mismo motivo: el plan describe como se paga lo
    comprometido, no puede prometer otra cosa.

    - Una cuota necesita monto **y** fecha. Media cuota no dice nada: ni
      cuanto ni cuando, y guardarla dejaria un plan que no se puede seguir.
    - La suma de las cuotas no puede pasar del monto comprometido. Pasarse
      seria un plan para pagar mas de lo que se acaba de acordar, y el papel
      diria dos cifras distintas sobre el mismo acuerdo.

    Que sume **menos** si se acepta: el operador puede dejar apuntadas las dos
    primeras cuotas y el resto para cuando se sepa.
    """
    if not installments:
        return []

    cuotas = []

    for numero, monto, fecha in installments:
        if monto is None and fecha is None:
            continue

        if monto is None or fecha is None:
            raise ValidationError(
                f"La cuota {numero} necesita monto y fecha: con uno de los dos "
                f"no se sabe ni cuanto ni cuando."
            )

        if Decimal(monto) <= ZERO:
            raise ValidationError(
                f"El monto de la cuota {numero} debe ser mayor a cero."
            )

        cuotas.append((numero, Decimal(monto), fecha))

    total = sum((monto for _, monto, _ in cuotas), ZERO)

    if total > amount:
        raise ValidationError(
            f"Las cuotas suman S/ {total} y el compromiso es de S/ {amount}: "
            f"el plan no puede prometer mas de lo acordado."
        )

    return cuotas


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


def receipt_series_options(office=None):
    """Los talonarios que ofrece una ventanilla, en el orden en que los ofrece.

    Salen de las filas de ReceiptSequence, que es donde vive el correlativo:
    ofrecer una serie que no tiene fila obligaria a crearla al vuelo dentro
    del cobro, y el numero se emitiria sin el bloqueo que evita repetirlo.

    **Varian por oficina** porque un talonario es papel que esta en un cajon.
    Apata no puede emitir del block que vive en Oroya, y ofrecerselo invita a
    numerar algo que nadie tiene delante. El orden tambien es de la oficina:
    los tres «S003» salen en Jauja Cajas como SPEEDY, VELOCIDAD, RED OPTICA y
    en Huancayo El Tambo al reves, asi que lo dice la relacion.

    Sin oficina -o con una que el padron no nombra- se devuelve la lista
    completa. Es el mismo criterio que hace opcional la oficina en el cobro:
    un despliegue sin padron cargado sigue cobrando, porque la sede basta para
    saber que caja recibio el dinero, y quedarse sin series dejaria la
    ventanilla parada por una tabla que nadie lleno.

    R001 no esta entre ellas. Era el talonario propio del sistema, el que se
    uso mientras no habia padron, y sigue existiendo porque sus comprobantes
    ya se entregaron; lo que no hace es ofrecerse para cobrar de nuevo.

    Aqui no se asegura ninguno: el padron entra por migracion, y crear uno al
    vuelo para que la lista no quede vacia volveria a meter R001 por la puerta
    de atras en cada base recien creada.
    """
    if office is not None:
        propios = list(
            ReceiptSequence.objects.filter(
                is_active=True,
                office_links__office=office,
            ).order_by("office_links__position", "position", "label")
        )

        if propios:
            return propios

    return list(ReceiptSequence.objects.filter(is_active=True))


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
