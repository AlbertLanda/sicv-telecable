"""Reporte comercial diario por vendedor.

Una venta es una Subscription registrada: el vendedor es quien originó la
venta y registered_by quien la digitó. Son dos responsabilidades distintas y
este reporte conserva ambas.
"""

from collections import OrderedDict

from django.db.models import Q

from apps.services.models import Subscription


def sales_for_day(*, day, branch=None, seller=None):
    queryset = (
        Subscription.objects
        .filter(created_at__date=day)
        .select_related(
            "seller",
            "registered_by",
            "customer",
            "customer__branch",
            "address",
            "address__zone",
            "address__zone__branch",
            "service_type",
            "plan",
        )
        .order_by(
            "seller__first_name",
            "seller__last_name",
            "seller__username",
            "created_at",
            "pk",
        )
    )

    if branch is not None:
        queryset = queryset.filter(
            Q(address__zone__branch=branch)
            | Q(
                address__zone__isnull=True,
                customer__branch=branch,
            )
        )

    if seller is not None:
        queryset = queryset.filter(seller=seller)

    return queryset


def build_sales_report(*, day, branch=None, seller=None):
    rows = list(
        sales_for_day(
            day=day,
            branch=branch,
            seller=seller,
        )
    )

    by_seller = OrderedDict()

    for subscription in rows:
        key = subscription.seller_id
        label = (
            str(subscription.seller)
            if subscription.seller_id
            else "Sin vendedor atribuido"
        )

        if key not in by_seller:
            by_seller[key] = {
                "seller": subscription.seller,
                "label": label,
                "count": 0,
            }

        by_seller[key]["count"] += 1

    return {
        "day": day,
        "branch": branch,
        "seller": seller,
        "rows": rows,
        "summary": list(by_seller.values()),
        "total_sales": len(rows),
        "seller_count": sum(
            1 for item in by_seller.values()
            if item["seller"] is not None
        ),
    }
