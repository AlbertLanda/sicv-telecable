from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer, CustomerAddress
from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch
from apps.payments.balances import with_charge_balances
from apps.payments.models import Charge, Payment, PaymentAllocation
from apps.reports.dashboard import DashboardData, month_start
from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.models import OrderType, WorkOrder

User = get_user_model()


class DashboardTests(TestCase):
    def setUp(self):
        self.now = timezone.make_aware(datetime(2026, 10, 2, 16, 40))
        self.branch = Branch.objects.create(code="PANEL-A", name="Sede A")
        self.other = Branch.objects.create(code="PANEL-B", name="Sede B")
        self.admin = User.objects.create_user(
            username="panel_admin", role=User.Role.ADMIN, branch=self.branch
        )
        self.atc = User.objects.create_user(
            username="panel_atc", role=User.Role.ATC, branch=self.branch
        )
        self.customer = self.make_customer(1, self.branch)
        self.foreign = self.make_customer(2, self.other)
        self.disabled = self.make_customer(3, self.branch, is_active=False)
        service = ServiceType.objects.create(code="PANEL-IN", name="Internet prueba")
        plan = Plan.objects.create(
            code="PANEL-PLAN",
            name="Plan prueba",
            service_type=service,
            monthly_price=89,
        )
        address = CustomerAddress.objects.create(
            customer=self.customer,
            address="Dirección prueba",
            district="Distrito A",
            is_primary=True,
        )
        self.subscription = Subscription.objects.create(
            customer=self.customer, address=address, service_type=service, plan=plan
        )
        self.order_type = OrderType.objects.create(
            code="PANEL-OT", name="Servicio Internet prueba"
        )
        self.data = DashboardData(
            branches=[self.branch], month=date(2026, 10, 1), now=self.now
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = self.branch.pk
        session.save()

    def make_customer(self, number, branch, **kwargs):
        return Customer.objects.create(
            code=f"PANEL-{number}",
            branch=branch,
            document_type="DNI",
            document_number=f"9900000{number}",
            first_name=f"Abonado prueba {number}",
            **kwargs,
        )

    def pay(
        self,
        amount,
        *,
        customer=None,
        branch=None,
        paid_at=None,
        status=Payment.Status.REGISTERED,
    ):
        return Payment.objects.create(
            customer=customer or self.customer,
            branch=branch or self.branch,
            amount=Decimal(amount),
            method=Payment.Method.CASH,
            received_by=self.admin,
            received_at=self.now - timedelta(days=40),
            paid_at=paid_at or self.now,
            status=status,
        )

    def charge(self, amount="89", customer=None, **kwargs):
        options = {
            "customer": customer or self.customer,
            "amount": Decimal(amount),
            "concept": Charge.Concept.OTHER,
            "description": "Cargo prueba",
            "due_date": date(2026, 9, 30),
        }
        options.update(kwargs)
        return Charge.objects.create(**options)

    def order(self, age, status=WorkOrder.Status.PENDING, **kwargs):
        order = WorkOrder.objects.create(
            order_number=f"PANEL-OT-{WorkOrder.objects.count()}",
            order_type=self.order_type,
            subscription=self.subscription,
            branch=self.branch,
            created_by=self.admin,
            status=status,
            **kwargs,
        )
        WorkOrder.objects.filter(pk=order.pk).update(
            created_at=self.now - timedelta(hours=age)
        )
        return order

    def web(self, kind=None, **params):
        url = (
            reverse("reports:dashboard_detail", args=[kind])
            if kind
            else reverse("reports:dashboard")
        )
        with patch("apps.reports.dashboard_views.timezone.now", return_value=self.now):
            return self.client.get(url, {"month": "2026-10", **params})

    def test_income_uses_payment_date_status_and_receiving_branch(self):
        self.pay("79")
        self.pay("15", customer=self.foreign)
        self.pay("200", branch=self.other)
        self.pay("80", status=Payment.Status.PENDING)
        self.pay("90", status=Payment.Status.VOIDED)
        self.pay("40", paid_at=self.now - timedelta(days=3))
        self.pay("30", paid_at=self.now + timedelta(hours=1))
        self.assertEqual(self.data.summary()["income"], Decimal("94"))
        self.assertEqual(self.data.summary()["payment_count"], 2)
        detail = self.web("income")
        self.assertEqual(detail.context["total_amount"], Decimal("94"))
        self.assertEqual(detail.context["page_obj"].paginator.count, 2)
        self.assertContains(detail, "Sin recibo")

    def test_legacy_registered_payment_without_paid_at_is_not_invented_as_income(self):
        payment = self.pay("79")
        Payment.objects.filter(pk=payment.pk).update(paid_at=None)
        self.assertEqual(self.data.summary()["income"], 0)
        self.assertEqual(self.data.summary()["undated_payments"], 1)
        self.assertContains(self.web(), "sin fecha real de pago")

    def test_active_counts_records_once_with_multiple_addresses_and_services(self):
        CustomerAddress.objects.create(
            customer=self.customer,
            address="Otra dirección",
            district="Otro",
            is_primary=False,
        )
        Subscription.objects.create(
            customer=self.customer,
            address=self.subscription.address,
            service_type=self.subscription.service_type,
            plan=self.subscription.plan,
            service_number=2,
        )
        self.assertEqual(self.data.summary()["active"], 1)
        detail = self.web("active")
        self.assertEqual(detail.context["page_obj"].paginator.count, 1)
        self.assertEqual(detail.context["rows"][0]["district"], "Distrito A")

    def test_sql_balances_match_customer_debt_for_earned_discounts_and_voids(self):
        charge = self.charge(
            early_discount=10,
            discount_deadline=date(2026, 9, 29),
            status=Charge.Status.PARTIALLY_PAID,
        )
        paid = self.pay("79")
        PaymentAllocation.objects.create(
            payment=paid, charge=charge, amount=79, discount=10
        )
        pending = self.pay("20", status=Payment.Status.PENDING)
        PaymentAllocation.objects.create(payment=pending, charge=charge, amount=20)
        queried = with_charge_balances(
            Charge.objects.filter(pk=charge.pk), self.data.today
        ).get()
        self.assertEqual(queried.dashboard_balance, charge.balance_on(self.data.today))
        self.assertEqual(queried.dashboard_balance, 0)
        self.assertEqual(self.data.summary()["debtor_count"], 0)
        Payment.objects.filter(pk=paid.pk).update(status=Payment.Status.VOIDED)
        queried = with_charge_balances(
            Charge.objects.filter(pk=charge.pk), self.data.today
        ).get()
        self.assertEqual(queried.dashboard_balance, charge.balance_on(self.data.today))
        self.assertEqual(queried.dashboard_balance, Decimal("89"))

    def test_debt_excludes_future_cancelled_paid_disabled_and_foreign(self):
        self.charge("50")
        self.charge("15", due_date=date(2026, 8, 1))
        self.charge("30", due_date=self.data.today)
        self.charge("40", due_date=date(2026, 10, 20))
        self.charge("60", status=Charge.Status.CANCELLED)
        self.charge("70", status=Charge.Status.PAID)
        self.charge("100", customer=self.foreign)
        self.charge("100", customer=self.disabled)
        summary = self.data.summary()
        self.assertEqual(summary["debt"], Decimal("65"))
        self.assertEqual(summary["debtor_count"], 1)
        self.assertEqual(summary["debt_rate"], 100)
        detail = self.web("debt", age="61_plus")
        self.assertEqual(detail.context["total_amount"], Decimal("65"))
        self.assertEqual(detail.context["rows"][0]["days"], 62)
        self.assertEqual(self.data.debtors("1_30").count(), 0)

    def test_current_discount_matches_balance_without_join_multiplication(self):
        charge = self.charge(
            "100", early_discount=10, discount_deadline=date(2026, 10, 3)
        )
        for amount in ("10", "15"):
            PaymentAllocation.objects.create(
                payment=self.pay(amount), charge=charge, amount=amount
            )
        queried = with_charge_balances(
            Charge.objects.filter(pk=charge.pk), self.data.today
        ).get()
        self.assertEqual(queried.dashboard_balance, charge.balance_on(self.data.today))
        self.assertEqual(self.data.summary()["debt"], Decimal("65"))

    def test_order_threshold_is_strict_and_terminal_states_are_excluded(self):
        self.order(48)
        self.order(48.01, status=WorkOrder.Status.REPROGRAMMED)
        self.order(100, status=WorkOrder.Status.ATTENDED)
        self.order(100, status=WorkOrder.Status.CANCELLED)
        self.order(1)
        self.assertEqual(self.data.summary()["pending_orders"], 3)
        self.assertEqual(self.data.summary()["critical_orders"], 1)
        detail = self.web("orders", age="over_48")
        self.assertEqual(detail.context["page_obj"].paginator.count, 1)
        self.assertContains(detail, "Órdenes pendientes con más de 48 horas")
        self.assertEqual(self.data.orders("24_48").count(), 1)
        self.assertEqual(self.data.orders("0_24").count(), 1)

    def test_panel_and_detail_require_permission_and_consolidation_is_separate(self):
        self.client.force_login(self.atc)
        for kind in (None, "active", "income", "debt", "orders"):
            self.assertEqual(self.web(kind).status_code, 403)
        self.atc.user_permissions.add(
            Permission.objects.get(codename="view_operational_dashboard")
        )
        self.client.force_login(self.atc)
        self.assertEqual(self.web().status_code, 200)
        for kind in (None, "income", "active"):
            self.assertEqual(self.web(kind, scope="consolidated").status_code, 403)
        self.assertEqual(self.web("active", branch=self.other.pk).status_code, 400)

    def test_consolidated_counts_and_branch_filter_do_not_leak_current_scope(self):
        self.pay("10")
        self.pay("20", customer=self.foreign, branch=self.other)
        self.charge("30")
        self.charge("40", customer=self.foreign)
        panel = self.web(scope="consolidated")
        self.assertEqual(panel.status_code, 200)
        self.assertEqual(panel.context["summary"]["active"], 2)
        self.assertEqual(panel.context["summary"]["income"], Decimal("30"))
        self.assertEqual(panel.context["summary"]["debt"], Decimal("70"))
        self.assertEqual(
            sum(row["summary"]["income"] for row in panel.context["branch_comparison"]),
            Decimal("30"),
        )
        detail = self.web("income", scope="consolidated", branch=self.other.pk)
        self.assertEqual(detail.context["total_amount"], Decimal("20"))
        self.assertEqual(detail.context["rows"][0]["branch"], self.other.name)

    def test_search_and_pagination_keep_scope_month_and_global_total(self):
        for _ in range(25):
            self.pay("10")
        detail = self.web(
            "income", q=self.customer.document_number, per_page=20, page=2
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.context["rows"]), 5)
        self.assertEqual(detail.context["total_amount"], Decimal("250"))
        self.assertEqual(detail.context["page_obj"].paginator.count, 25)
        self.assertIn("scope=current", detail.context["page_query"])
        self.assertIn("month=2026-10", detail.context["page_query"])
        self.assertIn(
            "q=" + self.customer.document_number, detail.context["page_query"]
        )

    def test_bad_filters_and_unknown_kind_are_controlled(self):
        for params in (
            {"month": "2026-99"},
            {"scope": "unknown"},
            {"per_page": "bad"},
            {"age": "bad"},
            {"branch": "abc"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.web("income", **params).status_code, 400)
        self.assertEqual(self.web("missing").status_code, 404)
        self.assertEqual(self.web("income", q="9" * 120).status_code, 200)

    def test_month_windows_respect_lima_midnight_and_year_boundary(self):
        start = timezone.make_aware(datetime(2026, 10, 1))
        self.pay("10", paid_at=start - timedelta(seconds=1))
        self.pay("20", paid_at=start)
        self.assertEqual(self.data.summary()["income"], Decimal("20"))
        self.assertEqual(month_start(date(2026, 1, 30), -1), date(2025, 12, 1))

    def test_admin_landing_and_menu_are_available_without_manual_permissions(self):
        self.assertRedirects(self.client.get("/"), reverse("reports:dashboard"))
        self.assertContains(self.web(), "Panel administrador")
        self.assertEqual(self.web()["Cache-Control"], "private, no-store")
        self.client.force_login(self.atc)
        self.assertRedirects(self.client.get("/"), reverse("customers:search"))
        self.client.logout()
        self.assertRedirects(self.client.get("/"), reverse("login"))

    def test_empty_scope_and_missing_active_branch_fail_closed(self):
        empty = DashboardData(
            branches=[], month=date(2026, 10, 1), now=self.now
        ).summary()
        self.assertEqual(empty["active"], 0)
        self.assertEqual(empty["income"], 0)
        self.assertEqual(empty["debt"], 0)
        self.assertIsNone(empty["debt_rate"])
        self.admin.branch = None
        self.admin.save(update_fields=["branch"])
        session = self.client.session
        session.pop(ACTIVE_BRANCH_SESSION_KEY, None)
        session.save()
        with patch("apps.reports.dashboard_views.get_active_branch", return_value=None):
            self.assertEqual(self.web().status_code, 400)

    def test_debt_detail_has_no_query_per_charge(self):
        for _ in range(25):
            self.charge("1")
        with self.assertNumQueries(1):
            debt = list(self.data.debtors())
        self.assertEqual(debt[0]["balance"], Decimal("25"))

    def test_age_segments_cover_30_60_61_day_boundaries(self):
        self.charge("10", due_date=self.data.today - timedelta(days=30))
        self.charge(
            "20", customer=self.foreign, due_date=self.data.today - timedelta(days=60)
        )
        third = self.make_customer(4, self.branch)
        self.charge("30", customer=third, due_date=self.data.today - timedelta(days=61))
        data = DashboardData(
            branches=[self.branch, self.other], month=self.data.month, now=self.now
        )
        self.assertEqual(data.debtors("1_30").count(), 1)
        self.assertEqual(data.debtors("31_60").count(), 1)
        self.assertEqual(data.debtors("61_plus").count(), 1)

    def test_trend_matches_detail_for_previous_month_and_incomplete_current_month(self):
        self.pay("10", paid_at=self.now - timedelta(days=3))
        self.pay("20")
        rows = self.data.trend()
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[-2]["amount"], Decimal("10"))
        self.assertEqual(rows[-1]["amount"], Decimal("20"))
        self.assertTrue(rows[-1]["partial"])
        detail = self.web("income", month="2026-09")
        self.assertEqual(detail.context["total_amount"], rows[-2]["amount"])
