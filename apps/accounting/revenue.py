"""Recaudación local en PEN por fecha real de pago. No es emisión fiscal."""
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import uuid
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import BigIntegerField, Case, CharField, Count, Exists, F, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.payments.models import CashEntry, Issuer, Payment
from .access import available_issuers, require_access
from .models import RevenueRule

LIMA = ZoneInfo("America/Lima")
ZERO = Decimal("0.00")


def revenue_issuers(user):
    if not user.has_perm("accounting.view_revenue"):
        return Issuer.objects.none()
    return available_issuers(user)


def period_dates(period, anchor):
    if period not in RevenueRule.Period.values or not isinstance(anchor, date) or not 2000 <= anchor.year <= 2100:
        raise ValidationError("Seleccione un periodo y una fecha válidos entre 2000 y 2100.")
    if period == "DAY":
        return anchor, anchor
    if period == "YEAR":
        return date(anchor.year, 1, 1), date(anchor.year, 12, 31)
    last = monthrange(anchor.year, anchor.month)[1]
    if period == "FORTNIGHT":
        return anchor.replace(day=1 if anchor.day <= 15 else 16), anchor.replace(day=15 if anchor.day <= 15 else last)
    return anchor.replace(day=1), anchor.replace(day=last)


def attributed_payments():
    cash = CashEntry.objects.filter(payment_id=OuterRef("pk"), kind="PAYMENT")
    payments = Payment.objects.annotate(
        has_cash=Exists(cash),
        cash_issuer=Subquery(cash.values("issuer_id")[:1]),
        cash_ruc=Subquery(cash.values("issuer_ruc")[:1]),
        cash_reference=Subquery(cash.values("reference")[:1]),
    ).annotate(
        revenue_issuer=Case(When(has_cash=True, then=F("cash_issuer")), default=F("receipt__sequence__issuer_id"), output_field=BigIntegerField()),
        revenue_source=Case(When(has_cash=True, then=Value("Caja")), default=Value("Talonario actual"), output_field=CharField()),
    ).annotate(current_ruc=Subquery(Issuer.objects.filter(pk=OuterRef("revenue_issuer")).values("ruc")[:1]))
    return payments


def scoped_payments(user, issuer=None):
    issuers = revenue_issuers(user)
    if issuer:
        require_access(user, issuer, "accounting.view_revenue")
        issuers = issuers.filter(pk=issuer.pk)
    return attributed_payments().filter(revenue_issuer__in=issuers.values("pk"))


def latest_rules(issuers, period):
    latest = RevenueRule.objects.filter(issuer_id=OuterRef("issuer_id"), period=period).order_by("-revision")
    return {rule.issuer_id: rule for rule in RevenueRule.objects.filter(issuer__in=issuers, period=period, pk=Subquery(latest.values("pk")[:1]))}


def alert_state(rule, total, ruc):
    if rule is None or not rule.enabled:
        return {"label": "Sin alerta activa", "level": "none", "percent": None}
    if rule.issuer_ruc != ruc:
        return {"label": "Reconfigurar: el RUC cambió", "level": "review", "percent": None}
    percent = total * 100 / rule.limit
    if total >= rule.limit:
        label, level = "Umbral alcanzado", "reached"
    elif percent >= rule.warning_percent:
        label, level = "Cerca del umbral", "warning"
    else:
        label, level = "Por debajo del aviso", "normal"
    return {"label": label, "level": level, "percent": percent.quantize(Decimal(".01"))}


class RevenueReport:
    def __init__(self, *, user, period, anchor, issuer=None, branch=None, office=None, now=None):
        if not user.has_perm("accounting.view_revenue"):
            raise PermissionDenied
        self.now = now or timezone.now()
        self.period, self.start, self.end = period, *period_dates(period, anchor)
        self.issuer, self.branch, self.office = issuer, branch, office
        if office and branch and office.branch_id != branch.pk:
            raise ValidationError("La oficina no pertenece a la sede seleccionada.")
        self.issuers = revenue_issuers(user)
        if issuer:
            require_access(user, issuer, "accounting.view_revenue")
            self.issuers = self.issuers.filter(pk=issuer.pk)
        base = scoped_payments(user, issuer).filter(status="REGISTERED")
        begin = datetime.combine(self.start, time.min, LIMA)
        end = datetime.combine(self.end + timedelta(days=1), time.min, LIMA)
        dated = base.filter(paid_at__gte=begin, paid_at__lt=end)
        valid = Q(has_cash=False) | Q(cash_ruc=F("current_ruc"))
        self.company_payments = dated.filter(valid, paid_at__lte=self.now)
        self.payments = self.company_payments
        self.missing_date = base.filter(paid_at__isnull=True).count()
        self.future = dated.filter(paid_at__gt=self.now).count()
        self.ruc_conflicts = dated.filter(has_cash=True).exclude(cash_ruc=F("current_ruc")).count()
        if branch:
            self.payments = self.payments.filter(branch=branch)
        if office:
            self.payments = self.payments.filter(office=office)

    def summary(self):
        # Una fila de cobro se cuenta una vez, sin joins con aplicaciones ni bancos.
        totals = self.payments.aggregate(total=Sum("amount"), count=Count("pk"),
            fallback=Count("pk", filter=Q(has_cash=False)))
        totals["total"] = totals["total"] or ZERO
        company = {r["revenue_issuer"]: r for r in self.company_payments.order_by().values("revenue_issuer").annotate(total=Sum("amount"), count=Count("pk"))}
        filtered = {r["revenue_issuer"]: r for r in self.payments.order_by().values("revenue_issuer").annotate(total=Sum("amount"), count=Count("pk"))}
        rules = latest_rules(self.issuers, self.period)
        repeated = set(Issuer.objects.filter(is_active=True, ruc__in=self.issuers.values("ruc")).order_by()
            .values("ruc").annotate(count=Count("pk")).filter(count__gt=1).values_list("ruc", flat=True))
        companies = []
        for issuer in self.issuers:
            entire = company.get(issuer.pk, {})
            scoped = filtered.get(issuer.pk, {})
            rule = rules.get(issuer.pk)
            total = entire.get("total", ZERO)
            alert = alert_state(rule, total, issuer.ruc)
            if issuer.ruc in repeated or not re.fullmatch(r"[0-9]{11}", issuer.ruc):
                alert = {"label": "Revisar RUC incompleto o repetido en el catálogo", "level": "review", "percent": None}
            companies.append({"issuer": issuer, "total": scoped.get("total", ZERO), "count": scoped.get("count", 0),
                "company_total": total, "rule": rule, "alert": alert})
        breakdown = list(self.payments.order_by().values("branch_id", "branch__code", "branch__name", "office_id", "office__code", "office__name", "method").annotate(total=Sum("amount"), count=Count("pk")).order_by("branch__name", "office__name", "method"))
        for item in breakdown:
            item["method_label"] = dict(Payment.Method.choices).get(item["method"], item["method"])
        daily = list(self.payments.order_by().annotate(day=TruncDate("paid_at", tzinfo=LIMA)).values("day").annotate(total=Sum("amount"), count=Count("pk")).order_by("day"))
        return {"totals": totals, "companies": companies, "breakdown": breakdown, "daily": daily}

    def detail(self):
        return self.payments.select_related("customer", "branch", "office", "receipt__sequence", "received_by").order_by("-paid_at", "-pk")


@transaction.atomic
def save_rule(*, actor, issuer_id, period, limit, warning_percent, enabled, reason, expected_pk, request_key):
    issuer = Issuer.objects.select_for_update().get(pk=issuer_id)
    require_access(actor, issuer, "accounting.manage_revenue_rules")
    if not actor.has_perm("accounting.view_revenue"):
        raise PermissionDenied
    if not re.fullmatch(r"[0-9]{11}", issuer.ruc) or Issuer.objects.filter(is_active=True, ruc=issuer.ruc).exclude(pk=issuer.pk).exists():
        raise ValidationError("Revise el catálogo: se requiere un RUC de 11 dígitos sin otra empresa activa con el mismo RUC.")
    try:
        amount = Decimal(str(limit))
        warning = int(warning_percent)
        key = uuid.UUID(str(request_key))
        expected = int(expected_pk)
        if (not amount.is_finite() or amount <= 0 or amount > Decimal("99999999999999.99")
                or amount != amount.quantize(Decimal(".01")) or not 1 <= warning <= 100
                or str(warning_percent) != str(warning) or expected < 0):
            raise ValueError
    except (ValueError, TypeError, InvalidOperation, AttributeError, OverflowError):
        raise ValidationError("Indique un importe positivo con dos decimales como máximo y un aviso entre 1 y 100 %.")
    reason = str(reason or "").strip()
    if period not in RevenueRule.Period.values or not reason or len(reason) > 500 or type(enabled) is not bool:
        raise ValidationError("Indique periodo, estado y motivo de hasta 500 caracteres.")
    payload = [issuer.pk, issuer.ruc, actor.pk, period, str(amount.quantize(Decimal(".01"))), warning, enabled, reason, expected]
    fingerprint = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    prior = RevenueRule.objects.filter(request_key=key).first()
    if prior:
        if prior.fingerprint != fingerprint:
            raise ValidationError("Este envío ya fue utilizado con otra configuración.")
        return prior
    latest = RevenueRule.objects.filter(issuer=issuer, period=period).first()
    if (latest.pk if latest else 0) != expected:
        raise ValidationError("Otra persona actualizó esta alerta. Recargue y revise la nueva versión antes de guardar.")
    try:
        with transaction.atomic():
            return RevenueRule.objects.create(issuer=issuer, issuer_ruc=issuer.ruc, period=period,
                revision=latest.revision + 1 if latest else 1, enabled=enabled, limit=amount, warning_percent=warning,
                reason=reason, actor=actor, request_key=key, fingerprint=fingerprint)
    except IntegrityError:
        raise ValidationError("El envío ya está registrado. Recargue la configuración.")
