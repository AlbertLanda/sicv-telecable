"""Shared selections for administrative indicators and their detail pages.

Active means Customer.is_active, as in the current customer register. It does
not assert that every service is installed or paid. Income uses paid_at and
REGISTERED; debt is open overdue charges of enabled customer records.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Min, Prefetch, Q, Sum
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer, CustomerAddress
from apps.payments.balances import with_charge_balances
from apps.payments.models import Charge, Payment, ZERO
from apps.work_orders.models import WorkOrder


def month_start(day, offset=0):
    year, index = divmod(day.year * 12 + day.month - 1 + offset, 12)
    return day.replace(year=year, month=index + 1, day=1)


class DashboardData:
    def __init__(self, *, branches, month, now=None):
        self.branches = list(branches)
        self.branch_ids = [branch.pk for branch in self.branches]
        self.month = month
        self.now = now or timezone.now()
        self.today = timezone.localtime(self.now).date()

    def active_customers(self):
        return Customer.objects.filter(is_active=True, branch_id__in=self.branch_ids)

    def payments(self, month=None):
        month = month or self.month
        start = timezone.make_aware(datetime.combine(month, time.min))
        end = timezone.make_aware(datetime.combine(month_start(month, 1), time.min))
        return Payment.objects.filter(
            branch_id__in=self.branch_ids,
            status=Payment.Status.REGISTERED,
            paid_at__gte=start,
            paid_at__lt=end,
            paid_at__lte=self.now,
        )

    def overdue_charges(self):
        return with_charge_balances(
            Charge.objects.overdue(self.today).filter(
                customer__is_active=True,
                customer__branch_id__in=self.branch_ids,
            ),
            self.today,
        ).filter(dashboard_balance__gt=ZERO)

    def debtors(self, age="all"):
        rows = (
            self.overdue_charges()
            .order_by()
            .values("customer_id")
            .annotate(
                balance=Sum("dashboard_balance"),
                oldest_due_date=Min("due_date"),
            )
        )
        if age == "1_30":
            rows = rows.filter(oldest_due_date__gte=self.today - timedelta(days=30))
        elif age == "31_60":
            rows = rows.filter(
                oldest_due_date__gte=self.today - timedelta(days=60),
                oldest_due_date__lt=self.today - timedelta(days=30),
            )
        elif age == "61_plus":
            rows = rows.filter(oldest_due_date__lt=self.today - timedelta(days=60))
        return rows.order_by("oldest_due_date", "customer_id")

    def orders(self, age="all"):
        orders = WorkOrder.objects.filter(
            branch_id__in=self.branch_ids,
            status__in=WorkOrder.ACTIVE_STATUSES,
            created_at__lte=self.now,
        )
        if age == "over_48":
            orders = orders.filter(created_at__lt=self.now - timedelta(hours=48))
        elif age == "0_24":
            orders = orders.filter(created_at__gte=self.now - timedelta(hours=24))
        elif age == "24_48":
            orders = orders.filter(
                created_at__lt=self.now - timedelta(hours=24),
                created_at__gte=self.now - timedelta(hours=48),
            )
        return orders.order_by("created_at", "pk")

    def summary(self):
        paid = self.payments().aggregate(total=Sum("amount"), count=Count("pk"))
        debt = self.debtors().aggregate(
            total=Sum("balance"), count=Count("customer_id")
        )
        active = self.active_customers().count()
        orders = (
            self.orders()
            .order_by()
            .aggregate(
                total=Count("pk"),
                oldest=Min("created_at"),
                critical=Count(
                    "pk", filter=Q(created_at__lt=self.now - timedelta(hours=48))
                ),
            )
        )
        return {
            "active": active,
            "income": paid["total"] or ZERO,
            "payment_count": paid["count"],
            "debt": debt["total"] or ZERO,
            "debtor_count": debt["count"],
            "debt_rate": Decimal(debt["count"] * 100) / active if active else None,
            "pending_orders": orders["total"],
            "critical_orders": orders["critical"],
            "oldest_hours": (
                (self.now - orders["oldest"]).total_seconds() / 3600
                if orders["oldest"]
                else 0
            ),
            "undated_payments": Payment.objects.filter(
                branch_id__in=self.branch_ids,
                status=Payment.Status.REGISTERED,
                paid_at__isnull=True,
            ).count(),
        }

    def trend(self):
        # The current month is partial; previous months are not compared as
        # percentages until a historical comparison policy is validated.
        rows = []
        for offset in range(-5, 1):
            month = month_start(self.today, offset)
            rows.append(
                {
                    "month": month,
                    "amount": self.payments(month).aggregate(total=Sum("amount"))[
                        "total"
                    ]
                    or ZERO,
                    "partial": offset == 0,
                }
            )
        peak = max((row["amount"] for row in rows), default=ZERO)
        for row in rows:
            row["width"] = round(row["amount"] * 100 / peak) if peak else 0
        return rows

    def detail_queryset(self, kind, *, query="", age="all"):
        if kind == "active":
            rows = self.active_customers()
            if query:
                rows = rows.filter(customer_search(query))
            return (
                rows.select_related("branch")
                .prefetch_related(
                    Prefetch(
                        "addresses",
                        queryset=CustomerAddress.objects.filter(
                            is_active=True
                        ).order_by("-is_primary", "pk"),
                        to_attr="dashboard_addresses",
                    )
                )
                .order_by(
                    "paternal_surname",
                    "maternal_surname",
                    "first_name",
                    "business_name",
                    "pk",
                )
            )
        if kind == "income":
            rows = self.payments()
            if query:
                condition = (
                    customer_search(query, "customer__")
                    | Q(receipt__series__icontains=query)
                    | Q(reference__icontains=query)
                )
                if (
                    query.isascii()
                    and query.isdigit()
                    and len(query) <= 10
                    and int(query) <= 2147483647
                ):
                    condition |= Q(receipt__number=int(query))
                rows = rows.filter(condition)
            return rows.select_related(
                "branch", "customer", "receipt", "received_by"
            ).order_by("-paid_at", "-pk")
        if kind == "debt":
            rows = self.debtors(age)
            if query:
                rows = rows.filter(customer_search(query, "customer__"))
            return rows
        rows = self.orders(age)
        if query:
            rows = rows.filter(
                customer_search(query, "subscription__customer__")
                | Q(order_number__icontains=query)
                | Q(order_type__name__icontains=query),
            )
        return rows.select_related("branch", "order_type", "subscription__customer")

    def display_rows(self, kind, records, user):
        if kind == "debt":
            customers = Customer.objects.select_related("branch").in_bulk(
                row["customer_id"] for row in records
            )
        rows = []
        for record in records:
            if kind == "active":
                customer, branch = record, record.branch
            elif kind == "income":
                customer, branch = record.customer, record.branch
            elif kind == "debt":
                customer = customers[record["customer_id"]]
                branch = customer.branch
            else:
                customer = (
                    record.subscription.customer if record.subscription_id else None
                )
                branch = record.branch
            row = {
                "branch": branch.name,
                "customer": str(customer) if customer else "Sin abonado",
                "code": customer.code if customer else "—",
                "customer_url": (
                    reverse("customers:detail", args=[customer.pk])
                    if customer
                    and (
                        user.has_perm("customers.view_customer")
                        or user.has_perm("customers.change_customer")
                    )
                    else ""
                ),
            }
            if kind == "active":
                address = (
                    record.dashboard_addresses[0]
                    if record.dashboard_addresses
                    else None
                )
                row.update(
                    district=address.district if address else "—",
                    address=address.address if address else "—",
                )
            elif kind == "income":
                receipt = getattr(record, "receipt", None)
                row.update(
                    date=record.paid_at,
                    amount=record.amount,
                    document=receipt.full_number if receipt else "Sin recibo",
                    method=record.get_method_display(),
                    record_url=(
                        reverse("payments:receipt_detail", args=[receipt.pk])
                        if receipt and user.has_perm("payments.view_receipt")
                        else ""
                    ),
                )
            elif kind == "debt":
                row.update(
                    date=record["oldest_due_date"],
                    days=(self.today - record["oldest_due_date"]).days,
                    amount=record["balance"],
                )
            else:
                hours = (self.now - record.created_at).total_seconds() / 3600
                row.update(
                    date=record.created_at,
                    hours=hours,
                    days=int(hours // 24),
                    type=record.order_type.name or "Sin clasificar",
                    document=record.order_number,
                    status=record.get_status_display(),
                    record_url=(
                        reverse("work_orders:detail", args=[record.pk])
                        if record.subscription_id
                        and user.has_perm("work_orders.view_workorder")
                        else ""
                    ),
                )
            rows.append(row)
        return rows


def customer_search(query, prefix=""):
    condition = Q()
    for field in (
        "code",
        "document_number",
        "first_name",
        "paternal_surname",
        "maternal_surname",
        "business_name",
    ):
        condition |= Q(**{f"{prefix}{field}__icontains": query})
    return condition
