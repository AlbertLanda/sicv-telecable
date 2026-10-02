"""Muestras identificadas para revisar las pestañas de un abonado en Azure QA."""
import calendar
import os
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

SAMPLE_ROUTE = "qa.customer_tabs.v1"
SAMPLE_LABEL = "[MUESTRA QA]"
SAMPLE_TITLE = "MUESTRA QA - SIN VALIDEZ TRIBUTARIA"


def sample_path(customer):
    return f"/customers/{customer.pk}/"


def _month_before(day, count):
    number = day.year * 12 + day.month - 1 - count
    year, month = divmod(number, 12)
    return date(year, month + 1, 1)


@transaction.atomic
def prepare_customer_samples(*, customer_code, actor, day=None):
    """Agrega una sola vez ejemplos nuevos; no modifica la contratación existente."""
    if os.environ.get("WEBSITE_SITE_NAME") != "sicv-telecable-qa":
        raise ValidationError("Las muestras solo se pueden cargar en sicv-telecable-qa.")
    from apps.audit.models import AuditEvent
    from apps.customers.models import Customer
    from apps.payments.models import Charge, Payment, ReceiptSequence
    from apps.payments.services import create_manual_charge, register_payment
    from apps.services.models import Subscription
    from apps.work_orders.services import create_incident_work_order

    # El mismo bloqueo que usa cobranza protege la carga frente a dos arranques.
    customer = Customer.objects.select_for_update().get(code=customer_code)
    existing = AuditEvent.objects.filter(route_name=SAMPLE_ROUTE, path=sample_path(customer)).first()
    if existing:
        return existing.changes, False
    if not actor.is_active or not all(actor.has_perm(p) for p in (
        "payments.add_charge", "payments.add_payment", "payments.void_payment",
        "work_orders.add_workorder", "work_orders.cancel_workorder",
    )):
        raise ValidationError("El responsable requiere permisos de deuda, cobranza y órdenes.")
    if not customer.is_active:
        raise ValidationError("El abonado debe estar activo para preparar las muestras.")

    subscription = (Subscription.objects.filter(customer=customer, is_active=True)
        .exclude(status=Subscription.Status.CANCELLED).order_by("pk").first())
    if subscription is None:
        raise ValidationError("Primero registre el servicio del abonado.")
    monthly_amount = Decimal(subscription.total_monthly_price).quantize(Decimal("0.01"))
    if monthly_amount <= 0:
        raise ValidationError("El servicio debe tener una mensualidad de referencia mayor a cero.")
    day = day or timezone.localdate()
    sequence, _ = ReceiptSequence.objects.get_or_create(
        code="QA-MUESTRAS-HYO", defaults={
            "series": "DEMOQA", "document_title": SAMPLE_TITLE,
            "label": "Muestras QA (sin validez tributaria)", "is_active": False,
            "autonumber": True, "issuer": None,
        },
    )
    if (sequence.series != "DEMOQA" or sequence.document_title != SAMPLE_TITLE
            or sequence.issuer_id is not None or sequence.is_active):
        raise ValidationError("El talonario reservado para muestras tiene otra configuración.")

    charges = []
    for months, state in ((3, "pagada"), (2, "con pago pendiente"), (1, "por cobrar")):
        period = _month_before(day, months)
        due = date(period.year, period.month, calendar.monthrange(period.year, period.month)[1])
        # Son cargos manuales de muestra, sin ocupar periodos del servicio real.
        charges.append(create_manual_charge(
            customer=customer, concept=Charge.Concept.MONTHLY,
            description=f"{SAMPLE_LABEL} Mensualidad {state}; importe de referencia del plan",
            amount=monthly_amount, due_date=due, period=period, issued_on=period,
            subscription=None, auto_update=False,
        ))
    charges.append(create_manual_charge(
        customer=customer, concept=Charge.Concept.OTHER,
        description=f"{SAMPLE_LABEL} Concepto ficticio para mostrar anulación de cobro",
        amount=Decimal("25.00"), due_date=day - timedelta(days=5),
        issued_on=day - timedelta(days=5), auto_update=False,
    ))

    payments, receipts = [], []
    for index, method, settled, reference in (
        (0, Payment.Method.CASH, True, "QA-EFECTIVO"),
        (1, Payment.Method.YAPE, False, "QA-YAPE-PENDIENTE"),
        (3, Payment.Method.TRANSFER, True, "QA-TRANSFERENCIA-ANULADA"),
    ):
        charge = charges[index]
        payment, receipt = register_payment(
            customer=customer, amount=charge.amount, method=method,
            branch=customer.branch, office=None, user=actor,
            reference=reference, note=f"{SAMPLE_LABEL} Dinero ficticio para demostración en QA.",
            allocations=[(charge, charge.amount)], series=sequence,
            settled=settled, full_monthly_only=True, day=day,
        )
        payments.append(payment)
        receipts.append(receipt)
    payments[-1].void(actor, f"{SAMPLE_LABEL} Ejemplo de anulación; no hubo movimiento bancario real.")

    order = create_incident_work_order(
        subscription=subscription, customer=customer, created_by=actor,
        reason_text=f"{SAMPLE_LABEL} Consulta remota ficticia para demostración",
        detail=f"{SAMPLE_LABEL} Ejemplo de incidencia NOC. No se modifica la instalación existente.",
    )
    order.cancel(user=actor, reason=f"{SAMPLE_LABEL} Caso ficticio cerrado por anulación para mostrar el historial.")

    data = {
        "sample_key": "customer_tabs_v1", "as_of": day.isoformat(),
        "monthly_reference": str(monthly_amount),
        "charges": [obj.pk for obj in charges], "payments": [obj.pk for obj in payments],
        "receipts": [obj.pk for obj in receipts], "orders": [order.pk],
    }
    AuditEvent.objects.create(
        actor=actor, branch=customer.branch, method="COMMAND", route_name=SAMPLE_ROUTE,
        path=sample_path(customer), description="Carga de muestras QA para pestañas del abonado",
        changes=data,
    )
    return data, True
