from decimal import Decimal

from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.payments.equipment_sales import create_equipment_sale
from apps.payments.models import (
    Charge,
    EquipmentProduct,
    EquipmentSale,
    Payment,
)
from apps.payments.services import register_payment
from apps.payments.tests.base import PaymentsTestCase
from apps.work_orders.models import WorkOrder


class EquipmentSaleTests(PaymentsTestCase):
    def sell(self, code):
        return create_equipment_sale(
            customer=self.customer,
            subscription=self.subscription,
            product=EquipmentProduct.objects.get(code=code),
            user=self.cashier,
        )

    def test_repeater_sale_creates_immediate_fixed_debt_and_installation_order(self):
        sale = self.sell("repetidor-4-antenas")

        self.assertEqual(sale.price_snapshot, Decimal("210.00"))
        self.assertEqual(sale.charge.amount, Decimal("210.00"))
        self.assertEqual(sale.charge.status, Charge.Status.PENDING)
        self.assertFalse(sale.charge.auto_update)
        self.assertIsNone(sale.charge.period)
        self.assertEqual(
            sale.charge.description,
            "VENTA REPETIDOR 4 ANTENAS",
        )

        self.assertEqual(sale.work_order.order_type.code, "REQUIREMENT")
        self.assertEqual(sale.work_order.reason.code, "REPEATER")
        self.assertEqual(
            sale.work_order.attention_type,
            WorkOrder.AttentionType.FIELD,
        )
        self.assertIn("REPETIDOR 4 ANTENAS", sale.work_order.detail)
        self.assertNotIn("210", sale.work_order.detail)

    def test_mesh_sale_creates_190_debt_and_specific_installation_order(self):
        sale = self.sell("cubo-mesh")

        self.assertEqual(sale.price_snapshot, Decimal("190.00"))
        self.assertEqual(sale.charge.amount, Decimal("190.00"))
        self.assertEqual(sale.work_order.reason.code, "MESH_INSTALL")
        self.assertIn("CUBO MESH", sale.work_order.detail)

    def test_product_price_change_does_not_revalue_previous_sale(self):
        product = EquipmentProduct.objects.get(code="repetidor-4-antenas")
        sale = self.sell(product.code)

        product.current_price = Decimal("230.00")
        product.save(update_fields=["current_price", "updated_at"])

        sale.refresh_from_db()
        sale.charge.refresh_from_db()

        self.assertEqual(sale.price_snapshot, Decimal("210.00"))
        self.assertEqual(sale.charge.amount, Decimal("210.00"))

    def test_partial_payment_leaves_equipment_debt_partially_paid(self):
        sale = self.sell("repetidor-4-antenas")

        register_payment(
            customer=self.customer,
            amount=Decimal("100.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(sale.charge, Decimal("100.00"))],
        )

        sale.charge.refresh_from_db()

        self.assertEqual(
            sale.charge.status,
            Charge.Status.PARTIALLY_PAID,
        )
        self.assertEqual(
            sale.charge.balance,
            Decimal("110.00"),
        )

    def test_sale_keeps_charge_and_order_linked_in_one_audit_record(self):
        sale = self.sell("cubo-mesh")

        stored = EquipmentSale.objects.select_related(
            "charge",
            "work_order",
            "product",
        ).get(pk=sale.pk)

        self.assertEqual(stored.charge.customer, self.customer)
        self.assertEqual(stored.work_order.subscription, self.subscription)
        self.assertEqual(stored.product.code, "cubo-mesh")


class EquipmentSaleWebTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.operator = self.make_user(
            "equipment_operator",
            permissions=("view_charge", "add_charge"),
        )
        self.operator.user_permissions.add(
            Permission.objects.get(
                codename="add_workorder",
                content_type__app_label="work_orders",
            )
        )
        self.login(self.operator)

        self.url = reverse(
            "payments:equipment_sale_create",
            kwargs={"pk": self.customer.pk},
        )

    def test_screen_lists_confirmed_products_and_prices(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "REPETIDOR 4 ANTENAS")
        self.assertContains(response, "210.00")
        self.assertContains(response, "CUBO MESH")
        self.assertContains(response, "190.00")

    def test_post_creates_sale_debt_and_work_order(self):
        product = EquipmentProduct.objects.get(code="cubo-mesh")

        response = self.client.post(
            self.url,
            {
                "subscription": self.subscription.pk,
                "product": product.pk,
            },
        )

        self.assertRedirects(
            response,
            reverse("payments:debt", kwargs={"pk": self.customer.pk}),
        )

        sale = EquipmentSale.objects.get(customer=self.customer)
        self.assertEqual(sale.product, product)
        self.assertEqual(sale.charge.amount, Decimal("190.00"))
        self.assertEqual(sale.work_order.reason.code, "MESH_INSTALL")
