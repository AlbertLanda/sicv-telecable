"""
Pruebas de la creación centralizada de órdenes de trabajo.

Cubren el servicio create_work_order() y el correlativo transaccional
generate_order_number(): validaciones previas a persistir, estado inicial,
trazabilidad de created_by, unicidad del número y atomicidad.

Limitación conocida: SQLite no aplica bloqueos de fila reales, por lo que
aquí no se simula concurrencia verdadera. Lo que sí se verifica es que el
correlativo nunca reutiliza un número y que un fallo revierte tanto la orden
como el consumo del correlativo. El comportamiento bajo concurrencia real en
PostgreSQL está documentado en docs/work_orders_workflow.md.
"""

from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.services.models import Subscription
from apps.work_orders.models import WorkOrder, WorkOrderSequence
from apps.work_orders.services import (
    create_work_order,
    format_order_number,
    generate_order_number,
)
from apps.work_orders.tests.base import WorkOrderTestCase


class CreateWorkOrderTests(WorkOrderTestCase):
    """Camino feliz y trazabilidad de la orden recién creada."""

    def test_creates_valid_work_order(self):
        order = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
            reason=self.installation_reason,
            detail="Instalación de cliente nuevo.",
        )

        self.assertIsNotNone(order.pk)
        self.assertEqual(order.subscription, self.subscription)
        self.assertEqual(order.order_type, self.installation_type)
        self.assertEqual(order.reason, self.installation_reason)
        self.assertEqual(order.detail, "Instalación de cliente nuevo.")
        self.assertEqual(WorkOrder.objects.count(), 1)

    def test_new_order_starts_pending(self):
        order = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
        )

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(order.assigned_technician)
        self.assertIsNone(order.result)
        self.assertIsNone(order.started_at)
        self.assertIsNone(order.attended_at)

    def test_created_by_is_the_executing_user(self):
        order = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
        )

        self.assertEqual(order.created_by, self.atc_user)

    def test_branch_and_zone_default_from_subscription(self):
        """La sede sale del cliente y la zona de la dirección del servicio."""
        order = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
        )

        self.assertEqual(order.branch, self.customer.branch)
        self.assertEqual(order.zone, self.subscription.address.zone)

    def test_order_number_uses_official_format(self):
        order = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
        )

        expected = format_order_number(timezone.localdate().year, 1)

        self.assertEqual(order.order_number, expected)


class CreateWorkOrderValidationTests(WorkOrderTestCase):
    """Reglas que deben rechazarse ANTES de persistir nada."""

    def _create(self, **kwargs):
        defaults = {
            "subscription": self.subscription,
            "order_type": self.installation_type,
            "created_by": self.atc_user,
        }

        defaults.update(kwargs)

        return create_work_order(**defaults)

    def test_rejects_missing_user(self):
        with self.assertRaises(ValidationError):
            self._create(created_by=None)

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_inactive_user(self):
        with self.assertRaises(ValidationError):
            self._create(created_by=self.inactive_technician)

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_missing_subscription(self):
        with self.assertRaises(ValidationError):
            self._create(subscription=None)

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_disabled_subscription(self):
        self.subscription.is_active = False
        self.subscription.save(update_fields=["is_active", "updated_at"])

        with self.assertRaises(ValidationError):
            self._create()

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_cancelled_subscription(self):
        self.subscription.status = Subscription.Status.CANCELLED
        self.subscription.save(update_fields=["status", "updated_at"])

        with self.assertRaises(ValidationError):
            self._create()

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_subscription_of_another_customer(self):
        other_customer = Customer.objects.create(
            code="CLI002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="12345678",
            first_name="María",
            paternal_surname="Torres",
            maternal_surname="Vega",
        )

        with self.assertRaises(ValidationError):
            self._create(customer=other_customer)

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_accepts_matching_customer(self):
        order = self._create(customer=self.customer)

        self.assertEqual(order.subscription.customer, self.customer)

    def test_rejects_inactive_order_type(self):
        self.installation_type.is_active = False
        self.installation_type.save(update_fields=["is_active", "updated_at"])

        with self.assertRaises(ValidationError):
            self._create()

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_subtype_from_another_order_type(self):
        with self.assertRaises(ValidationError):
            self._create(subtype=self.temporary_subtype)

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_reason_from_another_order_type(self):
        with self.assertRaises(ValidationError):
            self._create(reason=self.cut_reason)

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_cause_from_another_order_type(self):
        with self.assertRaises(ValidationError):
            self._create(cause=self.cut_cause)

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_branch_of_another_customer(self):
        other_branch = Branch.objects.create(code="SED02", name="Sede Jauja")

        with self.assertRaises(ValidationError):
            self._create(branch=other_branch)

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_zone_of_another_branch(self):
        other_branch = Branch.objects.create(code="SED03", name="Sede Oroya")

        foreign_zone = Zone.objects.create(
            branch=other_branch,
            name="Zona Sur",
        )

        with self.assertRaises(ValidationError):
            self._create(zone=foreign_zone)

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_accepts_zone_of_the_same_branch(self):
        another_zone = Zone.objects.create(
            branch=self.branch,
            name="Zona Este",
        )

        order = self._create(zone=another_zone)

        self.assertEqual(order.zone, another_zone)


class CreateWorkOrderSubscriptionStateTests(WorkOrderTestCase):
    """Crear una OT registra trabajo pendiente; no ejecuta la instalación."""

    def test_installation_order_keeps_subscription_in_presale(self):
        create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
        )

        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.status,
            Subscription.Status.PRESALE,
        )
        self.assertIsNone(self.subscription.installation_date)

    def test_other_order_types_do_not_touch_subscription_status(self):
        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status", "updated_at"])

        for order_type in (
            self.cut_type,
            self.reconnection_type,
            self.transfer_type,
        ):
            with self.subTest(order_type=order_type.code):
                create_work_order(
                    subscription=self.subscription,
                    order_type=order_type,
                    created_by=self.atc_user,
                )

                self.subscription.refresh_from_db()

                self.assertEqual(
                    self.subscription.status,
                    Subscription.Status.ACTIVE,
                )
                self.assertIsNone(self.subscription.cut_date)
                self.assertIsNone(self.subscription.reconnection_date)


class OrderNumberSequenceTests(WorkOrderTestCase):
    """El correlativo no repite ni reutiliza números."""

    def test_sequence_starts_at_one(self):
        with transaction.atomic():
            number = generate_order_number(year=2026)

        self.assertEqual(number, "OT-2026-000001")

    def test_sequence_does_not_reuse_numbers(self):
        numbers = []

        with transaction.atomic():
            for _ in range(25):
                numbers.append(generate_order_number(year=2026))

        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertEqual(numbers[0], "OT-2026-000001")
        self.assertEqual(numbers[-1], "OT-2026-000025")

        sequence = WorkOrderSequence.objects.get(year=2026)

        self.assertEqual(sequence.last_number, 25)

    def test_sequence_is_independent_per_year(self):
        with transaction.atomic():
            first_2026 = generate_order_number(year=2026)
            first_2027 = generate_order_number(year=2027)
            second_2026 = generate_order_number(year=2026)

        self.assertEqual(first_2026, "OT-2026-000001")
        self.assertEqual(first_2027, "OT-2027-000001")
        self.assertEqual(second_2026, "OT-2026-000002")

    def test_consecutive_orders_get_unique_numbers(self):
        orders = [
            create_work_order(
                subscription=self.subscription,
                order_type=self.installation_type,
                created_by=self.atc_user,
            )
            for _ in range(5)
        ]

        numbers = [order.order_number for order in orders]

        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertEqual(
            WorkOrder.objects.values("order_number").distinct().count(),
            5,
        )

    def test_number_is_not_derived_from_last_order_id(self):
        """
        Borrar la última orden no debe hacer que el correlativo retroceda:
        el número vive en WorkOrderSequence, no en la tabla de órdenes.
        """
        first = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
        )

        first.delete()

        second = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
        )

        self.assertNotEqual(second.order_number, first.order_number)
        self.assertEqual(
            second.order_number,
            format_order_number(timezone.localdate().year, 2),
        )


class CreateWorkOrderAtomicityTests(WorkOrderTestCase):
    """Un fallo no puede dejar una orden ni un correlativo a medias."""

    def test_rolls_back_everything_when_saving_fails(self):
        year = timezone.localdate().year

        with patch.object(
            WorkOrder,
            "save",
            side_effect=RuntimeError("fallo simulado"),
        ):
            with self.assertRaises(RuntimeError):
                create_work_order(
                    subscription=self.subscription,
                    order_type=self.installation_type,
                    created_by=self.atc_user,
                )

        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertFalse(
            WorkOrderSequence.objects.filter(
                year=year,
                last_number__gt=0,
            ).exists()
        )

    def test_duplicate_number_does_not_create_a_second_order(self):
        """
        Si el correlativo devolviera un número ya usado (corrupción o
        intervención manual), la unicidad de order_number frena la creación
        y no queda una segunda orden.
        """
        first = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
        )

        with patch(
            "apps.work_orders.services.generate_order_number",
            return_value=first.order_number,
        ):
            with self.assertRaises(ValidationError):
                create_work_order(
                    subscription=self.subscription,
                    order_type=self.installation_type,
                    created_by=self.atc_user,
                )

        self.assertEqual(WorkOrder.objects.count(), 1)
        self.assertEqual(
            WorkOrder.objects.filter(order_number=first.order_number).count(),
            1,
        )

    def test_failed_creation_does_not_burn_the_next_number(self):
        with patch.object(
            WorkOrder,
            "save",
            side_effect=RuntimeError("fallo simulado"),
        ):
            with self.assertRaises(RuntimeError):
                create_work_order(
                    subscription=self.subscription,
                    order_type=self.installation_type,
                    created_by=self.atc_user,
                )

        order = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
        )

        self.assertEqual(
            order.order_number,
            format_order_number(timezone.localdate().year, 1),
        )
