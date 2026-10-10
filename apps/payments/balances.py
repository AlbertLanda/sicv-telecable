"""SQL counterpart of Charge.balance_on, without one query per charge."""

from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest

from .models import DebtAdjustment, Payment, PaymentAllocation, ZERO


def with_charge_balances(charges, day):
    money = DecimalField(max_digits=16, decimal_places=2)
    applied = (
        PaymentAllocation.objects.filter(
            charge_id=OuterRef("pk"),
            payment__status=Payment.Status.REGISTERED,
        )
        .order_by()
        .values("charge_id")
        .annotate(cash=Sum("amount"), discount=Sum("discount"))
    )
    zero = Value(ZERO, output_field=money)
    adjustments = DebtAdjustment.objects.filter(charge_id=OuterRef("pk"), status="APPROVED").order_by().values("charge_id").annotate(total=Sum("amount"))
    offered_discount = Case(
        When(discount_deadline__gte=day, then=F("early_discount")),
        default=zero,
        output_field=money,
    )
    return charges.annotate(
        dashboard_balance=Greatest(
            ExpressionWrapper(
                F("amount")
                - Coalesce(Subquery(adjustments.values("total")[:1]), zero)
                - Coalesce(Subquery(applied.values("cash")[:1]), zero)
                - Greatest(offered_discount, Coalesce(Subquery(applied.values("discount")[:1]), zero)),
                output_field=money,
            ),
            zero,
            output_field=money,
        ),
    )
