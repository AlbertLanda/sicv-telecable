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

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.services.models import Subscription
from apps.work_orders.models import (
    IncidentDetail,
    OrderType,
    WorkOrder,
    WorkOrderSequence,
    WorkOrderFieldSheet,
)
from apps.work_orders.services import (
    close_incident_attention,
    create_incident_work_order,
    create_work_order,
    format_order_number,
    generate_order_number,
    start_incident_attention,
    get_subscription_technical_context,
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

    def test_seller_is_optional_and_persists_when_sent(self):
        """
        Revisión del 03/09: `seller` registra qué vendedor originó la venta.
        Es opcional -no cambia nada si no se envía- y, cuando se envía, debe
        quedar tal cual en la orden.
        """
        order_without_seller = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
        )

        self.assertIsNone(order_without_seller.seller)

        other_subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.other_address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
            service_number=2,
        )

        order_with_seller = create_work_order(
            subscription=other_subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
            seller=self.seller,
        )

        self.assertEqual(order_with_seller.seller, self.seller)

class CreateIncidentWorkOrderTests(WorkOrderTestCase):
    """Reglas específicas de creación de incidencias NOC."""

    def setUp(self):
        super().setUp()

        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(
            update_fields=["status", "updated_at"]
        )

    def test_creates_incident_with_system_attention(self):
        order = create_incident_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
            reason_text="Cliente reporta que no tiene internet.",
            detail="Se solicita validación por NOC.",
        )

        self.assertIsNotNone(order.pk)
        self.assertEqual(order.order_type.code, "INCIDENT")
        self.assertEqual(
            order.attention_type,
            WorkOrder.AttentionType.SYSTEM,
        )
        self.assertEqual(order.status, WorkOrder.Status.PENDING)

    def test_creates_incident_detail_automatically(self):
        order = create_incident_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
            reason_text="Cliente reporta pérdida total del servicio.",
        )

        self.assertTrue(
            IncidentDetail.objects.filter(
                work_order=order
            ).exists()
        )

        self.assertEqual(
            IncidentDetail.objects.get(work_order=order).work_order,
            order,
        )

    def test_persists_free_text_reason(self):
        order = create_incident_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
            reason_text="  Cliente indica navegación intermitente.  ",
        )

        self.assertEqual(
            order.reason_text,
            "Cliente indica navegación intermitente.",
        )

        self.assertIsNone(order.reason)

    def test_incident_has_no_field_technician_or_schedule(self):
        order = create_incident_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
            reason_text="Cliente reporta lentitud.",
        )

        self.assertIsNone(order.assigned_technician)
        self.assertIsNone(order.scheduled_at)
        self.assertIsNone(order.scheduled_date)

    def test_rejects_empty_reason(self):
        with self.assertRaises(ValidationError):
            create_incident_work_order(
                subscription=self.subscription,
                created_by=self.atc_user,
                reason_text="   ",
            )

        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertEqual(IncidentDetail.objects.count(), 0)

    def test_rejects_too_short_reason(self):
        with self.assertRaises(ValidationError):
            create_incident_work_order(
                subscription=self.subscription,
                created_by=self.atc_user,
                reason_text="No",
            )

        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertEqual(IncidentDetail.objects.count(), 0)

class IncidentAttentionWorkflowTests(WorkOrderTestCase):
    """Flujo remoto de atención de incidencias por NOC."""

    def setUp(self):
        super().setUp()

        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(
            update_fields=["status", "updated_at"]
        )

        self.noc_user = User.objects.create_user(
            username="noc1",
            password="test1234",
            role=User.Role.NOC,
            branch=self.branch,
        )

        self.incident = create_incident_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
            reason_text="Cliente reporta pérdida total de conectividad.",
            detail="Validar remotamente parámetros del servicio.",
        )

    def test_noc_can_start_incident(self):
        before = timezone.now()

        order = start_incident_attention(
            self.incident,
            user=self.noc_user,
            remarks="NOC inicia diagnóstico remoto.",
        )

        after = timezone.now()

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            WorkOrder.Status.IN_PROGRESS,
        )
        self.assertIsNotNone(order.started_at)
        self.assertGreaterEqual(order.started_at, before)
        self.assertLessEqual(order.started_at, after)

    def test_start_incident_creates_status_history(self):
        start_incident_attention(
            self.incident,
            user=self.noc_user,
            remarks="Inicio de revisión desde NOC.",
        )

        entry = self.incident.status_history.get(
            new_status=WorkOrder.Status.IN_PROGRESS
        )

        self.assertEqual(
            entry.previous_status,
            WorkOrder.Status.PENDING,
        )
        self.assertEqual(entry.changed_by, self.noc_user)
        self.assertEqual(
            entry.remarks,
            "Inicio de revisión desde NOC.",
        )

    def test_atc_cannot_start_incident_without_permission(self):
        with self.assertRaises(ValidationError):
            start_incident_attention(
                self.incident,
                user=self.atc_user,
            )

        self.incident.refresh_from_db()

        self.assertEqual(
            self.incident.status,
            WorkOrder.Status.PENDING,
        )
        self.assertIsNone(self.incident.started_at)

    def test_field_technician_cannot_start_incident(self):
        with self.assertRaises(ValidationError):
            start_incident_attention(
                self.incident,
                user=self.technician,
            )

        self.incident.refresh_from_db()

        self.assertEqual(
            self.incident.status,
            WorkOrder.Status.PENDING,
        )

    def test_incident_cannot_be_started_twice(self):
        start_incident_attention(
            self.incident,
            user=self.noc_user,
        )

        with self.assertRaises(ValidationError):
            start_incident_attention(
                self.incident,
                user=self.noc_user,
            )

        self.incident.refresh_from_db()

        self.assertEqual(
            self.incident.status,
            WorkOrder.Status.IN_PROGRESS,
        )

    def test_noc_can_close_incident(self):
        start_incident_attention(
            self.incident,
            user=self.noc_user,
        )

        order = close_incident_attention(
            self.incident,
            user=self.noc_user,
            attention_detail=(
                "Se reinició remotamente la ONU y se validó "
                "navegación estable con el cliente."
            ),
            observations="Cliente confirma servicio restablecido.",
            remarks="Incidencia resuelta remotamente.",
        )

        order.refresh_from_db()

        detail = IncidentDetail.objects.get(
            work_order=order
        )

        self.assertEqual(
            order.status,
            WorkOrder.Status.ATTENDED,
        )
        self.assertIsNotNone(order.attended_at)

        self.assertEqual(
            detail.attention_detail,
            (
                "Se reinició remotamente la ONU y se validó "
                "navegación estable con el cliente."
            ),
        )
        self.assertEqual(
            detail.observations,
            "Cliente confirma servicio restablecido.",
        )
        self.assertEqual(
            detail.attended_by,
            self.noc_user,
        )

    def test_close_incident_requires_attention_detail(self):
        start_incident_attention(
            self.incident,
            user=self.noc_user,
        )

        with self.assertRaises(ValidationError):
            close_incident_attention(
                self.incident,
                user=self.noc_user,
                attention_detail="   ",
            )

        self.incident.refresh_from_db()

        self.assertEqual(
            self.incident.status,
            WorkOrder.Status.IN_PROGRESS,
        )
        self.assertIsNone(self.incident.attended_at)

    def test_atc_cannot_close_incident_without_permission(self):
        start_incident_attention(
            self.incident,
            user=self.noc_user,
        )

        with self.assertRaises(ValidationError):
            close_incident_attention(
                self.incident,
                user=self.atc_user,
                attention_detail="Intento de cierre por ATC.",
            )

        self.incident.refresh_from_db()

        self.assertEqual(
            self.incident.status,
            WorkOrder.Status.IN_PROGRESS,
        )

    def test_incident_cannot_close_before_starting(self):
        with self.assertRaises(ValidationError):
            close_incident_attention(
                self.incident,
                user=self.noc_user,
                attention_detail="Diagnóstico final.",
            )

        self.incident.refresh_from_db()

        self.assertEqual(
            self.incident.status,
            WorkOrder.Status.PENDING,
        )

    def test_close_incident_creates_status_history(self):
        start_incident_attention(
            self.incident,
            user=self.noc_user,
        )

        close_incident_attention(
            self.incident,
            user=self.noc_user,
            attention_detail="Servicio restablecido remotamente.",
            remarks="Cierre NOC.",
        )

        entry = self.incident.status_history.get(
            new_status=WorkOrder.Status.ATTENDED
        )

        self.assertEqual(
            entry.previous_status,
            WorkOrder.Status.IN_PROGRESS,
        )
        self.assertEqual(entry.changed_by, self.noc_user)
        self.assertEqual(entry.remarks, "Cierre NOC.")

    def test_incident_observations_can_remain_empty(self):
        start_incident_attention(
            self.incident,
            user=self.noc_user,
        )

        close_incident_attention(
            self.incident,
            user=self.noc_user,
            attention_detail="Se resolvió mediante ajuste remoto.",
        )

        detail = IncidentDetail.objects.get(
            work_order=self.incident
        )

        self.assertEqual(detail.observations, "")
        self.assertEqual(
            detail.attended_by,
            self.noc_user,
        )

class SubscriptionTechnicalContextTests(WorkOrderTestCase):
    """Contexto técnico histórico mostrado a NOC."""

    def test_returns_none_when_subscription_has_no_technical_history(self):
        context = get_subscription_technical_context(
            self.subscription
        )

        self.assertIsNone(context)

    def test_returns_latest_field_sheet_data(self):
        order = self.create_assigned_order()

        WorkOrderFieldSheet.objects.create(
            work_order=order,
            nap="NAP-001",
            terminal="12",
            equipment_code="AA:BB:CC:DD:EE:FF",
            seal_number="PREC-100",
            notes="Instalación inicial operativa.",
            updated_by=self.technician,
        )

        context = get_subscription_technical_context(
            self.subscription
        )

        self.assertIsNotNone(context)
        self.assertEqual(context["source_order"], order)
        self.assertEqual(context["nap"], "NAP-001")
        self.assertEqual(context["terminal"], "12")
        self.assertEqual(
            context["equipment_code"],
            "AA:BB:CC:DD:EE:FF",
        )
        self.assertEqual(
            context["seal_number"],
            "PREC-100",
        )
        self.assertEqual(
            context["technician_notes"],
            "Instalación inicial operativa.",
        )
        self.assertEqual(
            context["field_updated_by"],
            self.technician,
        )

    def test_returns_liquidation_data_when_available(self):
        order = self.create_attended_order()

        liquidation = self.create_liquidation(
            order=order,
            network_element="NAP-020",
            network_port="7",
            equipment_serial="ONU-ABC123",
            signal_level_dbm="-21.50",
            technical_notes="Se dejó servicio estable.",
        )

        context = get_subscription_technical_context(
            self.subscription
        )

        self.assertIsNotNone(context)
        self.assertEqual(
            context["source_order"],
            order,
        )
        self.assertEqual(
            context["network_element"],
            "NAP-020",
        )
        self.assertEqual(
            context["network_port"],
            "7",
        )
        self.assertEqual(
            context["equipment_serial"],
            "ONU-ABC123",
        )
        self.assertEqual(
            context["signal_level_dbm"],
            liquidation.signal_level_dbm,
        )
        self.assertEqual(
            context["technical_notes"],
            "Se dejó servicio estable.",
        )

    def test_uses_most_recent_physical_order(self):
        older_order = self.create_assigned_order()

        WorkOrderFieldSheet.objects.create(
            work_order=older_order,
            nap="NAP-OLD",
            terminal="1",
            equipment_code="OLD-MAC",
            seal_number="OLD-SEAL",
            updated_by=self.technician,
        )

        newer_order = self.create_assigned_order(
            order_type=self.reconnection_type,
        )

        WorkOrderFieldSheet.objects.create(
            work_order=newer_order,
            nap="NAP-NEW",
            terminal="9",
            equipment_code="NEW-MAC",
            seal_number="NEW-SEAL",
            updated_by=self.technician,
        )

        context = get_subscription_technical_context(
            self.subscription
        )

        self.assertIsNotNone(context)
        self.assertEqual(
            context["source_order"],
            newer_order,
        )
        self.assertEqual(context["nap"], "NAP-NEW")
        self.assertEqual(
            context["equipment_code"],
            "NEW-MAC",
        )
        self.assertEqual(
            context["seal_number"],
            "NEW-SEAL",
        )

    def test_ignores_system_incident_as_technical_source(self):
        incident_type = OrderType.objects.get(
            code="INCIDENT"
        )

        incident = self.create_order(
            order_type=incident_type,
            attention_type=WorkOrder.AttentionType.SYSTEM,
            reason_text="Incidencia lógica.",
        )

        context = get_subscription_technical_context(
            self.subscription,
            exclude_order=incident,
        )

        self.assertIsNone(context)

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

    def test_rejects_seller_without_sales_role(self):
        """El vendedor debe tener rol Ventas, igual que el técnico asignado
        debe tener rol Técnico: un usuario de otra área no puede quedar
        registrado como quien originó la venta."""
        with self.assertRaises(ValidationError):
            self._create(seller=self.atc_user)

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_inactive_seller(self):
        with self.assertRaises(ValidationError):
            self._create(seller=self.inactive_seller)

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_accepts_active_seller_with_sales_role(self):
        order = self._create(seller=self.seller)

        self.assertEqual(order.seller, self.seller)

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

    def test_rejects_inactive_subtype(self):
        self.temporary_subtype.is_active = False
        self.temporary_subtype.save(
            update_fields=["is_active", "updated_at"]
        )

        with self.assertRaises(ValidationError):
            self._create(
                order_type=self.cut_type,
                subtype=self.temporary_subtype,
            )

        self.assertEqual(WorkOrder.objects.count(), 0)


    def test_rejects_inactive_reason(self):
        self.installation_reason.is_active = False
        self.installation_reason.save(
            update_fields=["is_active", "updated_at"]
        )

        with self.assertRaises(ValidationError):
            self._create(
                reason=self.installation_reason,
            )

        self.assertEqual(WorkOrder.objects.count(), 0)


    def test_rejects_inactive_cause(self):
        self.cut_cause.is_active = False
        self.cut_cause.save(
            update_fields=["is_active", "updated_at"]
        )

        with self.assertRaises(ValidationError):
            self._create(
                order_type=self.cut_type,
                cause=self.cut_cause,
            )

        self.assertEqual(WorkOrder.objects.count(), 0)


    def test_rejects_subscription_zone_from_another_branch(self):
        other_branch = Branch.objects.create(
            code="SED04",
            name="Sede Inconsistente",
        )

        foreign_zone = Zone.objects.create(
            branch=other_branch,
            name="Zona Inconsistente",
        )

        self.subscription.address.zone = foreign_zone
        self.subscription.address.save(
            update_fields=["zone", "updated_at"]
        )

        with self.assertRaises(ValidationError):
            self._create()

        self.assertEqual(WorkOrder.objects.count(), 0)


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
