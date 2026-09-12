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
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.services.models import Subscription

from .models import (
    Charge,
    ChargeConcept,
    Payment,
    PaymentAllocation,
    PaymentCommitment,
    Receipt,
    ReceiptSequence,
    ZERO,
    format_receipt_number,
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


def monthly_reference(customer):
    """Mensualidad del abonado, la base de todo prorrateo.

    Sale de su suscripcion activa: es la cifra que el operador tiene delante
    al emitir una mensualidad a mano y la que reparte el mes en dias. Sin
    suscripcion activa devuelve cero, y la pantalla lo dice en vez de
    calcular sobre esa nada.
    """
    active = (
        customer.subscriptions.filter(status=Subscription.Status.ACTIVE)
        .order_by("pk")
        .first()
    )

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
    """Los talonarios en uso, en el orden de la ventanilla.

    Salen de las filas de ReceiptSequence, que es donde vive el correlativo:
    ofrecer una serie que no tiene fila obligaria a crearla al vuelo dentro
    del cobro, y el numero se emitiria sin el bloqueo que evita repetirlo.

    R001 no esta entre ellas. Era el talonario propio del sistema, el que se
    uso mientras no habia padron, y sigue existiendo porque sus comprobantes
    ya se entregaron; lo que no hace es ofrecerse para cobrar de nuevo.

    Aqui no se asegura ninguno: el padron entra por migracion, y crear uno al
    vuelo para que la lista no quede vacia volveria a meter R001 por la puerta
    de atras en cada base recien creada.
    """
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
