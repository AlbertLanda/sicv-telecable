from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.models import User
from apps.services.models import Subscription
from apps.work_orders.api.queries import available_work_orders
from apps.work_orders.incident_derivation import derive_incident_to_fault
from apps.work_orders.incident_noc import take_incident
from apps.work_orders.models import OrderReason, OrderType, WorkOrder
from apps.work_orders.services import create_incident_work_order
from apps.work_orders.tests.base import WorkOrderTestCase


class IncidentDerivationTests(WorkOrderTestCase):
    """Una incidencia remota puede terminar en una nueva avería física."""

    def setUp(self):
        super().setUp()

        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status", "updated_at"])

        self.noc = User.objects.create_user(
            username="noc_derivacion",
            password="test1234",
            role=User.Role.NOC,
            branch=self.branch,
        )
        self.other_noc = User.objects.create_user(
            username="noc_derivacion_otro",
            password="test1234",
            role=User.Role.NOC,
            branch=self.branch,
        )

        self.fault_type = OrderType.objects.create(
            code="INTERNET_FAULT",
            name="AVERÍA INTERNET",
            is_active=True,
        )
        self.fault_type.service_types.add(self.service_type)
        self.fault_reason = OrderReason.objects.create(
            order_type=self.fault_type,
            code="NO_REMOTE_ACCESS",
            name="SIN ACCESO REMOTO",
            classification=OrderReason.Classification.TECHNICAL,
            is_active=True,
        )

        self.incident = create_incident_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
            reason_text="Cliente sin navegación desde la mañana.",
            detail="ATC solicita validación remota antes de enviar personal.",
        )
        take_incident(self.incident, self.noc)

    def derive(self, **overrides):
        values = {
            "fault_type": self.fault_type,
            "fault_reason": self.fault_reason,
            "diagnosis": "No hay acceso remoto y la ONT permanece fuera de línea.",
            "field_detail": "Revisar fibra, conectores y potencia óptica en domicilio.",
            "priority": WorkOrder.Priority.HIGH,
        }
        values.update(overrides)
        return derive_incident_to_fault(
            self.incident,
            self.noc,
            **values,
        )

    def test_derivation_creates_new_pending_field_fault(self):
        incident, fault = self.derive()

        incident.refresh_from_db()
        fault.refresh_from_db()

        self.assertEqual(incident.status, WorkOrder.Status.DERIVED)
        self.assertEqual(fault.status, WorkOrder.Status.PENDING)
        self.assertEqual(fault.attention_type, WorkOrder.AttentionType.FIELD)
        self.assertIsNone(fault.assigned_technician)
        self.assertEqual(fault.subscription, self.subscription)
        self.assertEqual(fault.order_type, self.fault_type)
        self.assertEqual(fault.reason, self.fault_reason)
        self.assertEqual(fault.priority, WorkOrder.Priority.HIGH)
        self.assertEqual(fault.created_by, self.noc)
        self.assertIn(self.incident.order_number, fault.detail)
        self.assertIn("Diagnóstico NOC", fault.detail)
        self.assertIn("Revisar fibra", fault.detail)

    def test_derivation_records_fault_number_in_incident_history(self):
        incident, fault = self.derive()

        history = incident.status_history.get(
            new_status=WorkOrder.Status.DERIVED
        )
        self.assertEqual(history.changed_by, self.noc)
        self.assertIn(fault.order_number, history.remarks)
        self.assertIn("No hay acceso remoto", history.remarks)

    def test_generated_fault_enters_shared_technician_pool(self):
        _, fault = self.derive()

        available_ids = set(
            available_work_orders().values_list("pk", flat=True)
        )
        self.assertIn(fault.pk, available_ids)

    def test_other_noc_cannot_derive_incident_owned_by_someone_else(self):
        with self.assertRaises(ValidationError):
            derive_incident_to_fault(
                self.incident,
                self.other_noc,
                fault_type=self.fault_type,
                fault_reason=self.fault_reason,
                diagnosis="Se requiere revisión física del enlace.",
                field_detail="Validar drop y conector del abonado.",
            )

        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, WorkOrder.Status.IN_PROGRESS)
        self.assertFalse(
            WorkOrder.objects.filter(
                order_type=self.fault_type,
                subscription=self.subscription,
            ).exists()
        )

    def test_incident_cannot_be_derived_twice(self):
        self.derive()

        with self.assertRaises(ValidationError):
            self.derive()

        self.assertEqual(
            WorkOrder.objects.filter(
                order_type=self.fault_type,
                subscription=self.subscription,
            ).count(),
            1,
        )

    def test_non_fault_order_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.derive(fault_type=self.cut_type, fault_reason=None)

        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, WorkOrder.Status.IN_PROGRESS)

    def test_current_handler_sees_derive_action(self):
        self.client.force_login(self.noc)

        response = self.client.get(
            reverse(
                "work_orders:incident_noc_detail",
                kwargs={"pk": self.incident.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Derivar a avería")
        self.assertContains(
            response,
            reverse(
                "work_orders:incident_derive_fault",
                kwargs={"pk": self.incident.pk},
            ),
        )

    def test_derive_view_creates_fault_and_redirects_to_incident_history(self):
        self.client.force_login(self.noc)
        url = reverse(
            "work_orders:incident_derive_fault",
            kwargs={"pk": self.incident.pk},
        )

        response = self.client.post(
            url,
            {
                "fault_type": self.fault_type.pk,
                "fault_reason": self.fault_reason.pk,
                "diagnosis": "No hay acceso remoto a la ONT del abonado.",
                "field_detail": "Revisar potencia, drop y conectores en campo.",
                "priority": WorkOrder.Priority.NORMAL,
            },
            follow=True,
        )

        self.assertRedirects(
            response,
            reverse(
                "work_orders:incident_noc_detail",
                kwargs={"pk": self.incident.pk},
            ),
        )
        self.assertContains(response, "derivada correctamente")
        self.assertContains(response, "Incidencia derivada a campo")

        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, WorkOrder.Status.DERIVED)
        self.assertEqual(
            WorkOrder.objects.filter(order_type=self.fault_type).count(),
            1,
        )
