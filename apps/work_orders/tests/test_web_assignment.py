"""
Pruebas del flujo web controlado de asignación de órdenes de trabajo.

Cubren WorkOrderAssignForm + WorkOrderAssignView: autenticación, permiso
funcional de despacho, elegibilidad del técnico y las garantías que la capa
web no puede relajar (la transición la ejecuta el dominio, la orden queda en
ASSIGNED y no en atención, y un POST manipulado no fuerza estado ni técnico).

Lo que aquí se verifica es que la vista NO abre puertas que el modelo ya
cerró. Las reglas de asignación en sí están probadas en test_assignment.py.
"""

from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.organization.models import Branch
from apps.services.models import Subscription
from apps.work_orders.models import (
    WorkOrder,
    WorkOrderAssignment,
    WorkOrderStatusHistory,
)
from apps.work_orders.tests.base import User, WorkOrderTestCase


class WorkOrderWebAssignmentTestCase(WorkOrderTestCase):
    """Escenario común: una OT pendiente y un despachador con permiso."""

    def setUp(self):
        super().setUp()

        self.order = self.create_order()

        self.url = reverse(
            "work_orders:assign",
            kwargs={"pk": self.order.pk},
        )

        self.customer_url = reverse(
            "customers:detail",
            kwargs={"pk": self.customer.pk},
        )

        # El despachador se define por PERMISO, no por rol: se le asigna el
        # permiso a un supervisor cualquiera para dejar claro que lo que
        # habilita la acción es assign_workorder y nada más.
        self.assignment_permission = Permission.objects.get(
            codename="assign_workorder",
            content_type__app_label="work_orders",
        )

        self.dispatcher = self.supervisor
        self.dispatcher.user_permissions.add(self.assignment_permission)

        # Sede distinta a la de la orden, con su propio técnico activo: es el
        # candidato que la vista debe rechazar aunque sea técnico y esté
        # activo.
        self.other_branch = Branch.objects.create(
            code="SED02",
            name="Sede Bagua",
        )

        self.foreign_technician = User.objects.create_user(
            username="tecnico_ajeno",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=self.other_branch,
        )

        self.client.login(username="supervisor1", password="test1234")

    def valid_payload(self, **overrides):
        """POST mínimo y correcto para despachar la orden."""
        payload = {
            "assigned_technician": self.technician.pk,
            "remarks": "Coordinar con el cliente antes de salir.",
        }

        payload.update(overrides)

        return payload

    def assertOrderUntouched(self, order=None, status=None, technician=None):
        """La orden conservó su estado y su técnico anteriores."""
        order = order or self.order

        expected_status = status or WorkOrder.Status.PENDING

        order.refresh_from_db()

        self.assertEqual(order.status, expected_status)
        self.assertEqual(order.assigned_technician, technician)


class WorkOrderAssignViewAccessTests(WorkOrderWebAssignmentTestCase):
    """Pruebas 2 y 3: autenticación y permiso funcional de despacho."""

    def test_authorized_user_sees_the_form(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("form", response.context)
        self.assertEqual(response.context["order"], self.order)

    def test_anonymous_user_cannot_open_the_form(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_anonymous_user_cannot_assign(self):
        self.client.logout()

        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertOrderUntouched()

    def test_authenticated_user_without_permission_cannot_open_form(self):
        self.client.logout()
        self.client.login(username="atc1", password="test1234")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_authenticated_user_without_permission_cannot_assign(self):
        self.client.logout()
        self.client.login(username="atc1", password="test1234")

        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(response.status_code, 403)
        self.assertOrderUntouched()
        self.assertFalse(WorkOrderAssignment.objects.exists())

    def test_add_workorder_permission_does_not_authorize_assignment(self):
        """Crear órdenes no habilita despacharlas: son atribuciones distintas."""
        self.client.logout()

        self.atc_user.user_permissions.add(
            Permission.objects.get(
                codename="add_workorder",
                content_type__app_label="work_orders",
            )
        )

        self.client.login(username="atc1", password="test1234")

        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(response.status_code, 403)
        self.assertOrderUntouched()

    def test_unknown_order_returns_not_found(self):
        url = reverse(
            "work_orders:assign",
            kwargs={"pk": self.order.pk + 999},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_user_without_permission_gets_403_even_for_unknown_order(self):
        """El 404 no debe servir para sondear qué órdenes existen."""
        self.client.logout()
        self.client.login(username="atc1", password="test1234")

        url = reverse(
            "work_orders:assign",
            kwargs={"pk": self.order.pk + 999},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)


class WorkOrderAssignViewSuccessTests(WorkOrderWebAssignmentTestCase):
    """Pruebas 1, 8 y 9: la asignación válida y sus efectos exactos."""

    def test_valid_request_assigns_the_order(self):
        response = self.client.post(self.url, self.valid_payload())

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(self.order.assigned_technician, self.technician)

        self.assertRedirects(response, self.customer_url)

    def test_assignment_is_persisted_for_the_selected_technician(self):
        """Prueba 9: el técnico guardado es exactamente el seleccionado."""
        self.client.post(
            self.url,
            self.valid_payload(assigned_technician=self.other_technician.pk),
        )

        self.order.refresh_from_db()

        self.assertEqual(
            self.order.assigned_technician,
            self.other_technician,
        )
        self.assertNotEqual(self.order.assigned_technician, self.technician)

    def test_assignment_history_records_who_dispatched(self):
        self.client.post(self.url, self.valid_payload())

        assignment = WorkOrderAssignment.objects.get(work_order=self.order)

        self.assertEqual(assignment.technician, self.technician)
        self.assertEqual(assignment.assigned_by, self.dispatcher)
        self.assertIsNone(assignment.unassigned_at)
        self.assertEqual(
            assignment.remarks,
            "Coordinar con el cliente antes de salir.",
        )

    def test_transition_goes_through_the_official_mechanism(self):
        """La vista delega en el dominio: hay historial de estado."""
        self.client.post(self.url, self.valid_payload())

        history = WorkOrderStatusHistory.objects.get(work_order=self.order)

        self.assertEqual(history.previous_status, WorkOrder.Status.PENDING)
        self.assertEqual(history.new_status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(history.changed_by, self.dispatcher)

    def test_assignment_does_not_start_the_attention(self):
        """Prueba 8: asignar despacha, no inicia la atención."""
        self.client.post(self.url, self.valid_payload())

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, WorkOrder.Status.ASSIGNED)
        self.assertNotEqual(self.order.status, WorkOrder.Status.IN_PROGRESS)
        self.assertIsNone(self.order.started_at)
        self.assertIsNone(self.order.attended_at)

    def test_assignment_does_not_touch_the_subscription(self):
        previous_status = self.subscription.status

        self.client.post(self.url, self.valid_payload())

        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.status, previous_status)
        self.assertEqual(
            Subscription.objects.filter(customer=self.customer).count(),
            1,
        )

    def test_assignment_does_not_register_an_operational_result(self):
        self.client.post(self.url, self.valid_payload())

        self.order.refresh_from_db()

        self.assertIsNone(self.order.result)
        self.assertIsNone(self.order.cause)

    def test_remarks_are_optional(self):
        response = self.client.post(
            self.url,
            self.valid_payload(remarks=""),
        )

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, WorkOrder.Status.ASSIGNED)
        self.assertRedirects(response, self.customer_url)

    def test_success_message_is_shown(self):
        response = self.client.post(
            self.url,
            self.valid_payload(),
            follow=True,
        )

        messages = [str(message) for message in response.context["messages"]]

        self.assertTrue(
            any(self.order.order_number in message for message in messages)
        )


class WorkOrderAssignEligibilityTests(WorkOrderWebAssignmentTestCase):
    """Pruebas 4, 5, 6 y 10: quién puede recibir la orden y quién no."""

    def eligible_choices(self):
        """Técnicos que el formulario ofrece realmente en pantalla."""
        response = self.client.get(self.url)

        field = response.context["form"].fields["assigned_technician"]

        return list(field.queryset)

    def test_only_eligible_technicians_are_offered(self):
        choices = self.eligible_choices()

        self.assertIn(self.technician, choices)
        self.assertIn(self.other_technician, choices)

        self.assertNotIn(self.inactive_technician, choices)
        self.assertNotIn(self.atc_user, choices)
        self.assertNotIn(self.supervisor, choices)
        self.assertNotIn(self.foreign_technician, choices)

    def test_inactive_technician_is_rejected(self):
        """Prueba 4: un técnico inactivo no puede recibir la orden."""
        response = self.client.post(
            self.url,
            self.valid_payload(
                assigned_technician=self.inactive_technician.pk,
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertOrderUntouched()

    def test_non_technician_user_is_rejected(self):
        """Prueba 5: un usuario administrativo no es técnico elegible."""
        response = self.client.post(
            self.url,
            self.valid_payload(assigned_technician=self.atc_user.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertOrderUntouched()

    def test_technician_from_another_branch_is_rejected(self):
        """Prueba 6: la sede de la orden acota el personal elegible."""
        response = self.client.post(
            self.url,
            self.valid_payload(
                assigned_technician=self.foreign_technician.pk,
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertOrderUntouched()

    def test_technician_is_required(self):
        response = self.client.post(
            self.url,
            self.valid_payload(assigned_technician=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "assigned_technician",
            response.context["form"].errors,
        )
        self.assertOrderUntouched()

    def test_rejected_assignment_leaves_no_history(self):
        """Prueba 11: un rechazo no deja asignaciones ni cambios a medias."""
        self.client.post(
            self.url,
            self.valid_payload(
                assigned_technician=self.foreign_technician.pk,
            ),
        )

        self.assertFalse(WorkOrderAssignment.objects.exists())
        self.assertFalse(WorkOrderStatusHistory.objects.exists())

    def test_failed_reassignment_keeps_the_previous_technician(self):
        """Prueba 11: reasignar mal no deja la orden sin técnico."""
        order = self.create_assigned_order()

        url = reverse("work_orders:assign", kwargs={"pk": order.pk})

        assignments_before = WorkOrderAssignment.objects.filter(
            work_order=order
        ).count()

        response = self.client.post(
            url,
            self.valid_payload(
                assigned_technician=self.inactive_technician.pk,
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertOrderUntouched(
            order=order,
            status=WorkOrder.Status.ASSIGNED,
            technician=self.technician,
        )

        self.assertEqual(
            WorkOrderAssignment.objects.filter(work_order=order).count(),
            assignments_before,
        )

        self.assertTrue(
            WorkOrderAssignment.objects
            .filter(
                work_order=order,
                technician=self.technician,
                unassigned_at__isnull=True,
            )
            .exists()
        )


class WorkOrderAssignManipulatedPostTests(WorkOrderWebAssignmentTestCase):
    """Prueba 10: el navegador no impone estado ni datos sensibles."""

    def test_posted_status_is_ignored(self):
        self.client.post(
            self.url,
            self.valid_payload(status=WorkOrder.Status.LIQUIDATED),
        )

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, WorkOrder.Status.ASSIGNED)

    def test_posted_started_at_is_ignored(self):
        self.client.post(
            self.url,
            self.valid_payload(started_at="2026-01-01 08:00"),
        )

        self.order.refresh_from_db()

        self.assertIsNone(self.order.started_at)
        self.assertEqual(self.order.status, WorkOrder.Status.ASSIGNED)

    def test_posted_order_number_and_author_are_ignored(self):
        original_number = self.order.order_number

        self.client.post(
            self.url,
            self.valid_payload(
                order_number="OT-9999-000999",
                created_by=self.technician.pk,
            ),
        )

        self.order.refresh_from_db()

        self.assertEqual(self.order.order_number, original_number)
        self.assertEqual(self.order.created_by, self.atc_user)

    def test_posted_priority_and_schedule_are_ignored(self):
        self.client.post(
            self.url,
            self.valid_payload(
                priority=WorkOrder.Priority.URGENT,
                scheduled_at="2026-01-01 08:00",
            ),
        )

        self.order.refresh_from_db()

        self.assertEqual(self.order.priority, WorkOrder.Priority.NORMAL)
        self.assertIsNone(self.order.scheduled_at)

    def test_assigned_by_cannot_be_imposed_from_the_post(self):
        self.client.post(
            self.url,
            self.valid_payload(assigned_by=self.atc_user.pk),
        )

        assignment = WorkOrderAssignment.objects.get(work_order=self.order)

        self.assertEqual(assignment.assigned_by, self.dispatcher)


class WorkOrderAssignInvalidStatusTests(WorkOrderWebAssignmentTestCase):
    """Prueba 7: una orden cerrada no puede forzarse a ASSIGNED."""

    def assertCannotAssign(self, status):
        order = self.create_order(status=status)

        url = reverse("work_orders:assign", kwargs={"pk": order.pk})

        response = self.client.post(url, self.valid_payload())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)

        self.assertOrderUntouched(order=order, status=status)

        self.assertFalse(
            WorkOrderAssignment.objects.filter(work_order=order).exists()
        )

    def test_cancelled_order_cannot_be_assigned(self):
        self.assertCannotAssign(WorkOrder.Status.CANCELLED)

    def test_attended_order_cannot_be_assigned(self):
        self.assertCannotAssign(WorkOrder.Status.ATTENDED)

    def test_liquidated_order_cannot_be_assigned(self):
        self.assertCannotAssign(WorkOrder.Status.LIQUIDATED)

    def test_rejected_order_cannot_be_assigned(self):
        self.assertCannotAssign(WorkOrder.Status.REJECTED)

    def test_in_progress_order_cannot_be_reassigned(self):
        """La atención ya empezó: reasignar es otra actividad del flujo."""
        order = self.create_order_in_progress()

        url = reverse("work_orders:assign", kwargs={"pk": order.pk})

        response = self.client.post(
            url,
            self.valid_payload(assigned_technician=self.other_technician.pk),
        )

        self.assertEqual(response.status_code, 200)

        self.assertOrderUntouched(
            order=order,
            status=WorkOrder.Status.IN_PROGRESS,
            technician=self.technician,
        )

    def test_closed_order_does_not_offer_the_form(self):
        order = self.create_order(status=WorkOrder.Status.CANCELLED)

        url = reverse("work_orders:assign", kwargs={"pk": order.pk})

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_be_assigned"])
        self.assertNotContains(response, "Asignar técnico")


class WorkOrderAssignUITests(WorkOrderWebAssignmentTestCase):
    """Prueba 12: la acción solo se ofrece a quien puede ejecutarla."""

    def test_user_with_permission_sees_the_assign_action(self):
        response = self.client.get(self.customer_url)

        self.assertContains(response, self.url)

    def test_user_without_permission_does_not_see_the_assign_action(self):
        self.client.logout()
        self.client.login(username="atc1", password="test1234")

        response = self.client.get(self.customer_url)

        self.assertNotContains(response, self.url)

    def test_closed_order_does_not_offer_the_action(self):
        self.order.status = WorkOrder.Status.CANCELLED
        self.order.save(update_fields=["status"])

        response = self.client.get(self.customer_url)

        self.assertNotContains(response, self.url)
