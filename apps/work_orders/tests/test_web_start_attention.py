"""
Pruebas del flujo web controlado de inicio de atención de órdenes.

Cubren WorkOrderStartAttentionForm + WorkOrderStartAttentionView:
autenticación, permiso funcional propio de inicio, y las garantías que la
capa web no puede relajar (la transición la ejecuta el dominio, la hora real
la pone el servidor, un GET no cambia nada y un POST manipulado no fuerza ni
el estado destino ni el técnico ni started_at).

Lo que aquí se verifica es que la vista NO abre puertas que el modelo ya
cerró. Las reglas del inicio en sí -qué estados admiten start_attention(),
qué registra y qué historial deja- están probadas en test_workflow.py.
"""

from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from apps.services.models import Subscription
from apps.work_orders.models import WorkOrder, WorkOrderStatusHistory
from apps.work_orders.tests.base import WorkOrderTestCase


class WorkOrderWebStartAttentionTestCase(WorkOrderTestCase):
    """Escenario común: una OT ya despachada y un operador con permiso."""

    def setUp(self):
        super().setUp()

        self.order = self.create_assigned_order()

        self.url = reverse(
            "work_orders:start",
            kwargs={"pk": self.order.pk},
        )

        self.customer_url = reverse(
            "customers:detail",
            kwargs={"pk": self.customer.pk},
        )

        # Quien inicia se define por PERMISO, no por rol: se le concede
        # start_workorder a un supervisor cualquiera para dejar claro que lo
        # que habilita la acción es el permiso y nada más. Se le añade
        # view_workorder porque el flujo real se lanza desde la bandeja.
        self.start_permission = Permission.objects.get(
            codename="start_workorder",
            content_type__app_label="work_orders",
        )

        self.view_permission = Permission.objects.get(
            codename="view_workorder",
            content_type__app_label="work_orders",
        )

        self.starter = self.supervisor
        self.starter.user_permissions.add(
            self.start_permission,
            self.view_permission,
        )

        self.client.login(username="supervisor1", password="test1234")

    def valid_payload(self, **overrides):
        """POST mínimo y correcto para iniciar la atención."""
        payload = {
            "remarks": "El técnico llegó al domicilio del cliente.",
        }

        payload.update(overrides)

        return payload

    def start_url_for(self, order):
        return reverse("work_orders:start", kwargs={"pk": order.pk})

    def assertOrderUntouched(self, order, status, started_at=None):
        """La orden conservó su estado y su hora de inicio anteriores."""
        order.refresh_from_db()

        self.assertEqual(order.status, status)
        self.assertEqual(order.started_at, started_at)

    def in_progress_history(self, order):
        return WorkOrderStatusHistory.objects.filter(
            work_order=order,
            new_status=WorkOrder.Status.IN_PROGRESS,
        )


class WorkOrderStartAttentionAccessTests(WorkOrderWebStartAttentionTestCase):
    """Pruebas 1, 2 y 3: autenticación y permiso funcional de inicio."""

    def test_authorized_user_sees_the_confirmation(self):
        """1. Acceso autorizado: 200 y contexto correcto."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("form", response.context)
        self.assertEqual(response.context["order"], self.order)
        self.assertEqual(response.context["customer"], self.customer)
        self.assertTrue(response.context["can_start_attention"])

    def test_anonymous_user_cannot_open_the_confirmation(self):
        """2. Usuario anónimo: redirección a login."""
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_anonymous_user_cannot_start_attention(self):
        self.client.logout()

        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertOrderUntouched(self.order, WorkOrder.Status.ASSIGNED)

    def test_authenticated_user_without_permission_cannot_open(self):
        """3. Sin permiso: 403 al abrir."""
        self.client.logout()
        self.client.login(username="atc1", password="test1234")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_authenticated_user_without_permission_cannot_start(self):
        """3. Sin permiso: 403 al enviar el POST."""
        self.client.logout()
        self.client.login(username="atc1", password="test1234")

        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(response.status_code, 403)
        self.assertOrderUntouched(self.order, WorkOrder.Status.ASSIGNED)
        self.assertFalse(self.in_progress_history(self.order).exists())

    def test_assign_permission_does_not_authorize_start(self):
        """Despachar no habilita iniciar: son atribuciones distintas."""
        self.client.logout()

        self.atc_user.user_permissions.add(
            Permission.objects.get(
                codename="assign_workorder",
                content_type__app_label="work_orders",
            )
        )

        self.client.login(username="atc1", password="test1234")

        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(response.status_code, 403)
        self.assertOrderUntouched(self.order, WorkOrder.Status.ASSIGNED)

    def test_change_permission_does_not_authorize_start(self):
        """Editar órdenes tampoco habilita iniciar la atención."""
        self.client.logout()

        self.atc_user.user_permissions.add(
            Permission.objects.get(
                codename="change_workorder",
                content_type__app_label="work_orders",
            )
        )

        self.client.login(username="atc1", password="test1234")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_permission_is_checked_before_looking_up_the_order(self):
        """
        Sin permiso se responde 403 incluso para una orden inexistente.

        Si la vista buscara la orden antes de autorizar, un 404 revelaría qué
        identificadores existen a quien no puede operar ninguno.
        """
        self.client.logout()
        self.client.login(username="atc1", password="test1234")

        response = self.client.get(
            reverse("work_orders:start", kwargs={"pk": 999999})
        )

        self.assertEqual(response.status_code, 403)

    def test_authorized_user_gets_404_for_unknown_order(self):
        response = self.client.get(
            reverse("work_orders:start", kwargs={"pk": 999999})
        )

        self.assertEqual(response.status_code, 404)


class WorkOrderStartAttentionSuccessTests(WorkOrderWebStartAttentionTestCase):
    """Pruebas 4, 5, 6, 7 y 16: el camino válido y su trazabilidad."""

    def test_assigned_order_moves_to_in_progress(self):
        """4. OT ASSIGNED con POST válido pasa a IN_PROGRESS."""
        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(response.status_code, 302)

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, WorkOrder.Status.IN_PROGRESS)

    def test_started_at_is_registered_by_the_domain(self):
        """5. Se registra la fecha y hora real de inicio."""
        before = timezone.now()

        self.client.post(self.url, self.valid_payload())

        after = timezone.now()

        self.order.refresh_from_db()

        self.assertIsNotNone(self.order.started_at)
        self.assertGreaterEqual(self.order.started_at, before)
        self.assertLessEqual(self.order.started_at, after)

    def test_status_history_is_created(self):
        """6. La transición deja constancia en WorkOrderStatusHistory."""
        self.client.post(self.url, self.valid_payload())

        history = self.in_progress_history(self.order)

        self.assertEqual(history.count(), 1)

        entry = history.get()

        self.assertEqual(entry.previous_status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(entry.new_status, WorkOrder.Status.IN_PROGRESS)

    def test_operator_is_traceable_in_the_history(self):
        """7. changed_by queda a nombre del usuario autenticado."""
        self.client.post(self.url, self.valid_payload())

        entry = self.in_progress_history(self.order).get()

        self.assertEqual(entry.changed_by, self.starter)

    def test_remarks_are_stored_in_the_history(self):
        """La observación opcional viaja al historial tal cual."""
        self.client.post(
            self.url,
            self.valid_payload(remarks="Cliente presente en el domicilio."),
        )

        entry = self.in_progress_history(self.order).get()

        self.assertEqual(entry.remarks, "Cliente presente en el domicilio.")

    def test_remarks_are_optional(self):
        """La observación no es obligatoria: sin ella el inicio procede."""
        response = self.client.post(self.url, {"remarks": ""})

        self.assertEqual(response.status_code, 302)

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, WorkOrder.Status.IN_PROGRESS)

    def test_success_message_and_redirect(self):
        """16. Mensaje de éxito visible y redirección correcta."""
        response = self.client.post(
            self.url,
            self.valid_payload(),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain[0][0],
            self.customer_url,
        )

        text = " ".join(
            str(message) for message in response.context["messages"]
        )

        self.assertIn(self.order.order_number, text)
        self.assertIn("iniciada", text.lower())

    def test_redirect_falls_back_to_the_customer_file(self):
        """
        Sin view_workorder no se redirige a la bandeja.

        Iniciar y ver la bandeja son permisos distintos: mandar a una
        pantalla prohibida convertiría un éxito en un 403.
        """
        self.starter.user_permissions.remove(self.view_permission)

        # El caché de permisos del usuario se resuelve una vez por petición,
        # pero el objeto de sesión vive en memoria: se fuerza un login nuevo.
        self.client.logout()
        self.client.login(username="supervisor1", password="test1234")

        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.customer_url)

    def test_subscription_effect_of_the_service_is_applied(self):
        """
        El inicio pasa por start_order_attention(), no solo por el modelo.

        Una instalación en preventa debe mover la suscripción a INSTALLATION:
        ese efecto vive en el servicio, así que su ausencia delataría que la
        vista llamó al método del modelo por su cuenta.
        """
        self.assertEqual(
            self.subscription.status,
            Subscription.Status.PRESALE,
        )

        self.client.post(self.url, self.valid_payload())

        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.status,
            Subscription.Status.INSTALLATION,
        )


class WorkOrderStartAttentionRejectionTests(WorkOrderWebStartAttentionTestCase):
    """Pruebas 8 a 13 y 17: estados no elegibles y errores de dominio."""

    def assertRejected(self, order, status, started_at=None):
        """El POST se informa en pantalla y la orden no se movió."""
        response = self.client.post(
            self.start_url_for(order),
            self.valid_payload(),
        )

        # Sin 500 y sin redirección: se vuelve al formulario con el mensaje
        # del dominio, que ya está redactado para el operador.
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())

        self.assertOrderUntouched(order, status, started_at=started_at)

        return response

    def test_pending_order_is_rejected(self):
        """8. Una OT PENDING no puede iniciarse."""
        order = self.create_order()

        self.assertRejected(order, WorkOrder.Status.PENDING)

        self.assertFalse(self.in_progress_history(order).exists())

    def test_in_progress_order_cannot_start_twice(self):
        """9. Una OT ya en atención se rechaza y no duplica historial."""
        order = self.create_order_in_progress()

        started_at = order.started_at

        self.assertRejected(
            order,
            WorkOrder.Status.IN_PROGRESS,
            started_at=started_at,
        )

        self.assertEqual(self.in_progress_history(order).count(), 1)

    def test_attended_order_is_rejected(self):
        """10. La atención ya terminó."""
        order = self.create_attended_order()

        self.assertRejected(
            order,
            WorkOrder.Status.ATTENDED,
            started_at=order.started_at,
        )

    def test_liquidated_order_is_rejected(self):
        """11. Una OT liquidada no vuelve a atención."""
        liquidation = self.create_liquidation()

        order = liquidation.work_order
        order.refresh_from_db()

        self.assertRejected(
            order,
            WorkOrder.Status.LIQUIDATED,
            started_at=order.started_at,
        )

    def test_cancelled_order_is_rejected(self):
        """12. Estado terminal: no admite inicio."""
        order = self.create_order(status=WorkOrder.Status.CANCELLED)

        self.assertRejected(order, WorkOrder.Status.CANCELLED)

    def test_rejected_order_is_rejected(self):
        order = self.create_order(status=WorkOrder.Status.REJECTED)

        self.assertRejected(order, WorkOrder.Status.REJECTED)

    def test_not_feasible_order_is_rejected(self):
        order = self.create_order(status=WorkOrder.Status.NOT_FEASIBLE)

        self.assertRejected(order, WorkOrder.Status.NOT_FEASIBLE)

    def test_order_without_technician_is_rejected_by_the_domain(self):
        """
        13. Sin técnico asignado no hay inicio posible.

        DERIVED es un estado iniciable, así que lo único que rechaza este
        POST es la condición de dominio, no la matriz de estados.
        """
        order = self.create_order(status=WorkOrder.Status.DERIVED)

        self.assertIsNone(order.assigned_technician)

        self.assertRejected(order, WorkOrder.Status.DERIVED)

        # El estado sí admite inicio, así que la pantalla debe señalar la
        # condición que realmente falta.
        response = self.client.get(self.start_url_for(order))

        self.assertContains(response, "todavía no tiene técnico asignado")

    def test_rejection_explains_the_status_before_the_technician(self):
        """
        Una OT pendiente tampoco tiene técnico, pero esa no es la razón.

        Si la pantalla culpara al técnico ausente, el operador intentaría
        despachar una orden que el dominio rechaza por su estado.
        """
        order = self.create_order()

        response = self.client.get(self.start_url_for(order))

        self.assertContains(response, "no admite iniciar la atención")
        self.assertNotContains(response, "todavía no tiene técnico asignado")

    def test_derived_order_with_technician_follows_the_domain(self):
        """
        DERIVED con técnico sí inicia, porque el dominio lo permite.

        La vista no reimplementa la regla: lo que start_attention() acepta,
        la pantalla acepta.
        """
        order = self.create_assigned_order()

        order.status = WorkOrder.Status.DERIVED
        order.save(update_fields=["status", "updated_at"])

        self.assertIn(order.status, WorkOrder.STARTABLE_STATUSES)

        response = self.client.post(
            self.start_url_for(order),
            self.valid_payload(),
        )

        self.assertEqual(response.status_code, 302)

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)

    def test_domain_error_is_shown_without_internal_traces(self):
        """17. El ValidationError se informa sin 500 y sin traza interna."""
        order = self.create_order()

        response = self.assertRejected(order, WorkOrder.Status.PENDING)

        text = response.content.decode()

        self.assertIn("No se puede iniciar la atención", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("ValidationError", text)

    def test_confirmation_of_a_non_startable_order_hides_the_action(self):
        """La pantalla no ofrece una acción que el dominio va a rechazar."""
        order = self.create_order()

        response = self.client.get(self.start_url_for(order))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_start_attention"])
        self.assertNotContains(response, "<form method=\"post\"")


class WorkOrderStartAttentionSafetyTests(WorkOrderWebStartAttentionTestCase):
    """Pruebas 14 y 15: el GET no opera y el POST no dicta el resultado."""

    def test_get_does_not_change_the_order(self):
        """14. Abrir la confirmación no ejecuta ninguna transición."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertOrderUntouched(self.order, WorkOrder.Status.ASSIGNED)
        self.assertFalse(self.in_progress_history(self.order).exists())

    def test_posted_status_is_ignored(self):
        """15. El estado destino no se toma de un parámetro del cliente."""
        self.client.post(
            self.url,
            self.valid_payload(
                status=WorkOrder.Status.ATTENDED,
                new_status=WorkOrder.Status.LIQUIDATED,
            ),
        )

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, WorkOrder.Status.IN_PROGRESS)

    def test_posted_started_at_is_ignored(self):
        """La hora real de inicio la pone el servidor, no el navegador."""
        before = timezone.now()

        self.client.post(
            self.url,
            self.valid_payload(started_at="2020-01-01 08:00"),
        )

        self.order.refresh_from_db()

        self.assertGreaterEqual(self.order.started_at, before)

    def test_posted_technician_is_ignored(self):
        """El inicio no reasigna: el técnico responsable no se toca."""
        self.client.post(
            self.url,
            self.valid_payload(
                assigned_technician=self.other_technician.pk,
            ),
        )

        self.order.refresh_from_db()

        self.assertEqual(self.order.assigned_technician, self.technician)

    def test_posted_user_does_not_replace_the_operator(self):
        """El responsable del historial sale de la sesión, no del POST."""
        self.client.post(
            self.url,
            self.valid_payload(
                user=self.atc_user.pk,
                changed_by=self.atc_user.pk,
            ),
        )

        entry = self.in_progress_history(self.order).get()

        self.assertEqual(entry.changed_by, self.starter)

    def test_the_form_only_accepts_remarks(self):
        """
        El contrato de entrada es una observación y nada más.

        Es lo que impide que un POST manipulado influya en la transición, y
        es el mismo contrato que deberá aceptar la futura API del técnico.
        """
        from apps.work_orders.forms import WorkOrderStartAttentionForm

        self.assertEqual(
            list(WorkOrderStartAttentionForm().fields),
            ["remarks"],
        )
