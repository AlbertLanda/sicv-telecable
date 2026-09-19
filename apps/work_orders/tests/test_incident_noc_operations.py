from datetime import timedelta

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.services.models import Subscription
from apps.work_orders.incident_noc import (
    cancel_incident,
    close_owned_incident,
    incident_current_handler,
    prior_incidents,
    release_incident,
    reschedule_incident,
    resume_incident,
    take_incident,
)
from apps.work_orders.models import WorkOrder
from apps.work_orders.services import create_incident_work_order
from apps.work_orders.tests.base import WorkOrderTestCase


class IncidentNocOperationsTests(WorkOrderTestCase):
    """Responsabilidad exclusiva y continuidad entre turnos del NOC."""

    def setUp(self):
        super().setUp()

        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status", "updated_at"])

        self.noc_one = User.objects.create_user(
            username="noc_operador_1",
            password="test1234",
            role=User.Role.NOC,
            branch=self.branch,
        )
        self.noc_two = User.objects.create_user(
            username="noc_operador_2",
            password="test1234",
            role=User.Role.NOC,
            branch=self.branch,
        )

        permissions = Permission.objects.filter(
            content_type__app_label="work_orders",
            codename__in=[
                "view_workorder",
                "view_incident",
                "start_incident",
                "close_incident",
                "cancel_workorder",
            ],
        )
        self.noc_one.user_permissions.add(*permissions)
        self.noc_two.user_permissions.add(*permissions)

        self.incident = create_incident_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
            reason_text="Cliente reporta cortes intermitentes de internet.",
            detail="Solicita validación remota por NOC.",
        )

    def test_take_incident_sets_exclusive_current_handler(self):
        order = take_incident(self.incident, self.noc_one)

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)
        self.assertEqual(incident_current_handler(order), self.noc_one)
        self.assertIsNotNone(order.started_at)

    def test_second_noc_cannot_take_incident_already_taken(self):
        take_incident(self.incident, self.noc_one)

        with self.assertRaises(ValidationError):
            take_incident(self.incident, self.noc_two)

        self.incident.refresh_from_db()
        self.assertEqual(
            incident_current_handler(self.incident),
            self.noc_one,
        )

    def test_only_current_handler_can_release_incident(self):
        take_incident(self.incident, self.noc_one)

        with self.assertRaises(ValidationError):
            release_incident(
                self.incident,
                self.noc_two,
                "Fin de turno del operador.",
            )

        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, WorkOrder.Status.IN_PROGRESS)

    def test_release_returns_incident_to_pending_without_losing_history(self):
        order = take_incident(self.incident, self.noc_one)
        first_started_at = order.started_at

        order = release_incident(
            order,
            self.noc_one,
            "Fin de turno. Continúa el siguiente operador NOC.",
        )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual(order.started_at, first_started_at)

        history = list(order.status_history.order_by("changed_at", "pk"))
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].new_status, WorkOrder.Status.IN_PROGRESS)
        self.assertEqual(history[0].changed_by, self.noc_one)
        self.assertEqual(history[1].new_status, WorkOrder.Status.PENDING)
        self.assertEqual(history[1].changed_by, self.noc_one)
        self.assertIn("Fin de turno", history[1].remarks)

    def test_another_noc_can_take_released_incident(self):
        order = take_incident(self.incident, self.noc_one)
        original_started_at = order.started_at
        order = release_incident(
            order,
            self.noc_one,
            "Cambio de turno NOC.",
        )

        order = take_incident(order, self.noc_two)
        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)
        self.assertEqual(incident_current_handler(order), self.noc_two)
        self.assertEqual(order.started_at, original_started_at)

    def test_reschedule_keeps_noc_schedule_separate_from_field_schedule(self):
        take_incident(self.incident, self.noc_one)
        scheduled_for = timezone.now() + timedelta(hours=5)

        order, reprogramming = reschedule_incident(
            self.incident,
            self.noc_one,
            scheduled_for=scheduled_for,
            reason="Cliente solicita llamada a las 17:00.",
            notes="Validar navegación con una PC conectada por cable.",
        )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.REPROGRAMMED)
        self.assertIsNone(order.scheduled_at)
        self.assertIsNone(order.scheduled_date)
        self.assertEqual(reprogramming.new_schedule, scheduled_for)
        self.assertEqual(reprogramming.created_by, self.noc_one)
        self.assertIn("Cliente solicita", reprogramming.reason)

    def test_any_authorized_noc_can_resume_reprogrammed_incident(self):
        take_incident(self.incident, self.noc_one)
        reschedule_incident(
            self.incident,
            self.noc_one,
            scheduled_for=timezone.now() + timedelta(hours=2),
            reason="Cliente solicita una llamada posterior.",
        )

        order = resume_incident(self.incident, self.noc_two)
        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)
        self.assertEqual(incident_current_handler(order), self.noc_two)

    def test_only_current_handler_can_close(self):
        take_incident(self.incident, self.noc_one)

        with self.assertRaises(ValidationError):
            close_owned_incident(
                self.incident,
                self.noc_two,
                attention_detail="Intento de cierre por otro NOC.",
            )

        order = close_owned_incident(
            self.incident,
            self.noc_one,
            attention_detail="Se corrigió configuración WAN.",
            observations="Cliente confirma navegación estable.",
        )
        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.ATTENDED)
        self.assertEqual(order.incident_detail.attended_by, self.noc_one)

    def test_close_view_rejects_a_noc_that_is_not_current_handler(self):
        take_incident(self.incident, self.noc_one)
        self.client.force_login(self.noc_two)

        response = self.client.get(
            reverse(
                "work_orders:incident_close",
                kwargs={"pk": self.incident.pk},
            ),
            follow=True,
        )

        self.assertRedirects(
            response,
            reverse(
                "work_orders:incident_noc_detail",
                kwargs={"pk": self.incident.pk},
            ),
        )
        self.assertContains(
            response,
            "Solo el responsable NOC actual puede finalizar esta incidencia.",
        )
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, WorkOrder.Status.IN_PROGRESS)

    def test_noc_detail_shows_customer_contact_numbers(self):
        self.customer.phone = "963200241"
        self.customer.secondary_phone = "964200242"
        self.customer.email = "cliente@example.com"
        self.customer.save(
            update_fields=["phone", "secondary_phone", "email", "updated_at"]
        )
        self.client.force_login(self.noc_one)

        response = self.client.get(
            reverse(
                "work_orders:incident_noc_detail",
                kwargs={"pk": self.incident.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "963200241")
        self.assertContains(response, "964200242")
        self.assertContains(response, "cliente@example.com")
        self.assertContains(response, "Llamar al principal")

    def test_noc_detail_is_the_operational_incident_workspace(self):
        take_incident(self.incident, self.noc_one)
        self.client.force_login(self.noc_one)

        response = self.client.get(
            reverse(
                "work_orders:incident_noc_detail",
                kwargs={"pk": self.incident.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TELECABLE · SISTEMA INTEGRADO COMERCIAL")
        self.assertContains(response, "Orden de Incidencia NOC")
        self.assertContains(response, "Bandeja NOC")
        self.assertContains(response, "Ficha del abonado")
        self.assertContains(response, "Imprimir orden")
        self.assertContains(response, "Liberar")
        self.assertContains(response, "Reprogramar contacto")
        self.assertContains(response, "Finalizar incidencia")
        self.assertNotContains(response, "Ficha general")

    def test_cancel_is_allowed_after_incident_was_taken(self):
        take_incident(self.incident, self.noc_one)

        order = cancel_incident(
            self.incident,
            self.noc_one,
            "Registro duplicado detectado durante la atención.",
        )
        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.CANCELLED)
        cancellation = order.status_history.filter(
            new_status=WorkOrder.Status.CANCELLED
        ).get()
        self.assertEqual(cancellation.changed_by, self.noc_one)
        self.assertIn("Registro duplicado", cancellation.remarks)

    def test_cancel_is_allowed_while_reprogrammed(self):
        take_incident(self.incident, self.noc_one)
        reschedule_incident(
            self.incident,
            self.noc_one,
            scheduled_for=timezone.now() + timedelta(days=1),
            reason="Cliente solicita retomar mañana.",
        )

        order = cancel_incident(
            self.incident,
            self.noc_two,
            "Cliente confirma que ya no requiere la atención.",
        )
        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.CANCELLED)

    def test_prior_incidents_are_limited_to_same_subscription(self):
        take_incident(self.incident, self.noc_one)
        close_owned_incident(
            self.incident,
            self.noc_one,
            attention_detail="Se reinició ONU y quedó estable.",
        )

        current = create_incident_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
            reason_text="Cliente vuelve a reportar intermitencia.",
        )

        history = prior_incidents(current)

        self.assertEqual([item.pk for item in history], [self.incident.pk])
