"""Casos de presentación agregados una sola vez al abonado autorizado de QA."""
import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .qa_samples import SAMPLE_LABEL, SAMPLE_TITLE, _month_before, sample_path

BILLING_SAMPLE_ROUTE = "qa.customer_billing.v1"


@transaction.atomic
def prepare_billing_examples(*, customer_code, actor, day=None):
    if os.environ.get("WEBSITE_SITE_NAME") != "sicv-telecable-qa":
        raise ValidationError("Las muestras solo se pueden cargar en sicv-telecable-qa.")
    from apps.audit.models import AuditEvent
    from apps.customers.models import Customer
    from apps.payments.models import Charge, ChargeComponent, Payment, ReceiptSequence
    from apps.payments.services import build_monthly_charge, create_manual_charge, register_payment
    from apps.services.models import BillingPolicy, Subscription

    customer = Customer.objects.select_for_update().get(code=customer_code)
    existing = AuditEvent.objects.filter(route_name=BILLING_SAMPLE_ROUTE, path=sample_path(customer)).first()
    if existing:
        return existing.changes, False
    if not customer.is_active or not actor.is_active or not all(actor.has_perm(p) for p in (
        "payments.add_charge", "payments.add_payment",
    )):
        raise ValidationError("Se requiere un abonado activo y permisos de deuda y cobranza.")
    original = Subscription.objects.filter(customer=customer, is_active=True).order_by("pk").first()
    if original is None:
        raise ValidationError("Primero registre el servicio del abonado.")
    policies = {p.code: p for p in BillingPolicy.objects.filter(code__in=("ANNIVERSARY_PP10", "CALENDAR_PP5"))}
    if len(policies) != 2:
        raise ValidationError("Faltan las políticas de pronto pago para preparar las muestras.")
    sequence, _ = ReceiptSequence.objects.get_or_create(code="QA-MUESTRAS-HYO", defaults={
        "series": "DEMOQA", "document_title": SAMPLE_TITLE,
        "label": "Muestras QA (sin validez tributaria)", "is_active": False,
        "autonumber": True, "issuer": None,
    })
    if (sequence.series != "DEMOQA" or sequence.document_title != SAMPLE_TITLE
            or sequence.issuer_id is not None or sequence.is_active):
        raise ValidationError("El talonario reservado para muestras tiene otra configuración.")
    day = day or timezone.localdate()
    charges, payments, receipts, cases = [], [], [], []

    def monthly(label, months, calendar=False, initial=False):
        period = _month_before(day, months)
        policy = policies["CALENDAR_PP5" if calendar else "ANNIVERSARY_PP10"]
        # Esta suscripción solo existe en memoria. Los ejemplos no ocupan los
        # periodos ni cambian la instalación o el plan del servicio contratado.
        scenario = Subscription(
            customer=customer, address=original.address, service_type=original.service_type,
            plan=original.plan, billing_policy=policy, status=Subscription.Status.ACTIVE,
            base_monthly_fee=Decimal("89.00"), annex_count=0, billing_cycle=14,
            installation_date=date(period.year, period.month, 7) if initial else date(2025, 1, 1),
        )
        charge = build_monthly_charge(scenario, period)
        charge.subscription = None
        charge.description = f"{SAMPLE_LABEL} {label}"
        charge.auto_update = False
        charge.full_clean()
        charge.save()
        if not calendar:
            ChargeComponent.objects.bulk_create([
                ChargeComponent(charge=charge, kind=ChargeComponent.Kind.MAIN, code="QA-PLAN",
                                description="Servicio del paquete", amount=Decimal("81.50")),
                ChargeComponent(charge=charge, kind=ChargeComponent.Kind.INCLUDED_APP, code="QA-APP",
                                description="APP TELECABLE", amount=Decimal("7.50")),
            ])
        charges.append(charge)
        return charge

    def case(label, charge, *, payment_day=None, fee=False, settled=True):
        items = [charge]
        if fee:
            extra = create_manual_charge(
                customer=customer, concept=Charge.Concept.OTHER,
                description=f"{SAMPLE_LABEL} Reconexión tras corte simulado por morosidad",
                amount=policies["ANNIVERSARY_PP10"].reconnection_fee,
                due_date=charge.due_date + timedelta(days=1), issued_on=charge.due_date + timedelta(days=1),
                auto_update=False,
            )
            charges.append(extra)
            items.append(extra)
        row = {"label": label, "charges": [c.pk for c in items], "receipt": None}
        if payment_day:
            allocations = [(c, c.balance_on(payment_day)) for c in items]
            received_at = timezone.make_aware(datetime.combine(payment_day, time(10)), timezone.get_current_timezone())
            payment, receipt = register_payment(
                customer=customer, amount=sum((value for _, value in allocations), Decimal("0.00")),
                method=Payment.Method.CASH if settled else Payment.Method.YAPE,
                branch=customer.branch, user=actor, reference=f"QA-CASO-{len(cases) + 1}",
                note=f"{SAMPLE_LABEL} {label}. Dinero ficticio; corte y reconexión simulados.",
                allocations=allocations, series=sequence, settled=settled,
                day=payment_day, received_at=received_at, full_monthly_only=True,
            )
            payments.append(payment)
            receipts.append(receipt)
            row["receipt"] = receipt.pk
        cases.append(row)

    charge = monthly("Plan 2026 · pronto pago de S/10", 2)
    case("2026 · paga hasta el día 10", charge, payment_day=charge.discount_deadline)
    charge = monthly("Plan 2026 · precio normal", 3)
    case("2026 · paga después del día 10", charge, payment_day=charge.discount_deadline + timedelta(days=1))
    charge = monthly("Plan 2026 · mensualidad y reconexión", 4)
    case("Corte simulado · paga mensualidad + S/15", charge, payment_day=charge.due_date + timedelta(days=1), fee=True)
    charge = monthly("Plan 2025 · pronto pago de S/5", 3, calendar=True)
    case("2025 · paga hasta el día 29", charge, payment_day=charge.discount_deadline)
    charge = monthly("Plan 2025 · precio normal", 4, calendar=True)
    case("2025 · paga después del día 29", charge, payment_day=charge.discount_deadline + timedelta(days=1))
    charge = monthly("Plan 2025 · primer mes desde instalación el día 7", 5, calendar=True, initial=True)
    case("2025 · primer mes proporcional", charge)
    charge = monthly("Plan 2026 · mensualidad por cobrar", 1)
    case("2026 · deuda con plazo de pronto pago", charge)
    charge = monthly("Plan 2026 · pago de reconexión por confirmar", 5)
    case("Corte simulado · pago por confirmar", charge, payment_day=charge.due_date + timedelta(days=1), fee=True, settled=False)

    data = {"sample_key": "billing_examples_v1", "as_of": day.isoformat(), "cases": cases,
            "charges": [c.pk for c in charges], "payments": [p.pk for p in payments],
            "receipts": [r.pk for r in receipts]}
    AuditEvent.objects.create(actor=actor, branch=customer.branch, method="COMMAND",
                             route_name=BILLING_SAMPLE_ROUTE, path=sample_path(customer),
                             description="Ejemplos QA de pronto pago, precio normal y reconexión", changes=data)
    return data, True
