"""
Pruebas 1 a 6: catálogos de orden y validación cruzada contra el tipo.

Cubre la creación de los catálogos base y la regla de que motivo, causa y
resultado deben pertenecer al mismo tipo de orden que la orden que los usa.
"""

from django.core.exceptions import ValidationError

from apps.work_orders.models import OrderReason, OrderType, WorkOrder
from apps.work_orders.tests.base import WorkOrderTestCase


class OrderCatalogTests(WorkOrderTestCase):

    def test_create_order_type(self):
        """1. Creación de OrderType."""
        order_type = OrderType.objects.create(
            code="FAULT",
            name="Avería",
        )

        self.assertEqual(order_type.code, "FAULT")
        self.assertTrue(order_type.is_active)
        self.assertEqual(str(order_type), "Avería")

    def test_create_order_reason(self):
        """2. Creación de OrderReason."""
        reason = OrderReason.objects.create(
            order_type=self.installation_type,
            code="MIGRATION",
            name="Migración de operador",
            classification=OrderReason.Classification.TECHNICAL,
        )

        self.assertEqual(reason.order_type, self.installation_type)
        self.assertIn("Migración de operador", str(reason))

    def test_create_work_order(self):
        """3. Creación de WorkOrder."""
        order = self.create_order(reason=self.installation_reason)

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual(order.priority, WorkOrder.Priority.NORMAL)
        self.assertEqual(order.subscription, self.subscription)
        self.assertIsNone(order.assigned_technician)
        self.assertIsNone(order.started_at)

    def test_reason_from_another_order_type_is_rejected(self):
        """4. Motivo perteneciente a otro tipo -> ValidationError."""
        order = self.create_order(
            order_type=self.installation_type,
            reason=self.cut_reason,
        )

        with self.assertRaises(ValidationError) as context:
            order.full_clean()

        self.assertIn("reason", context.exception.message_dict)

    def test_cause_from_another_order_type_is_rejected(self):
        """5. Causa perteneciente a otro tipo -> ValidationError."""
        order = self.create_order(
            order_type=self.installation_type,
            cause=self.cut_cause,
        )

        with self.assertRaises(ValidationError) as context:
            order.full_clean()

        self.assertIn("cause", context.exception.message_dict)

    def test_result_from_another_order_type_is_rejected(self):
        """6. Resultado perteneciente a otro tipo -> ValidationError."""
        order = self.create_order(
            order_type=self.installation_type,
            result=self.cut_success,
        )

        with self.assertRaises(ValidationError) as context:
            order.full_clean()

        self.assertIn("result", context.exception.message_dict)

    def test_subtype_from_another_order_type_is_rejected(self):
        """Complemento: el subtipo también se valida contra el tipo."""
        order = self.create_order(
            order_type=self.installation_type,
            subtype=self.temporary_subtype,
        )

        with self.assertRaises(ValidationError) as context:
            order.full_clean()

        self.assertIn("subtype", context.exception.message_dict)
