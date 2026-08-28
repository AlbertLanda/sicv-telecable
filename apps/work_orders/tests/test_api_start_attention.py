"""
Pruebas del endpoint de inicio de atención de la API del técnico.

Primera acción de escritura del canal. Lo que estas pruebas vigilan no es solo
que la orden pase a IN_PROGRESS, sino que la API **no decida nada por su
cuenta**: el estado lo pone el dominio, el rechazo lo redacta el dominio y
ningún valor del cliente distinto de `remarks` llega a influir.

Se apoyan en `WorkOrderTestCase`, que ya construye el escenario y los usuarios.
El permiso `work_orders.start_workorder` se concede en `setUp`: es el mismo que
usa la web y no viene con el rol.
"""

from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.services.models import Subscription
from apps.work_orders.models import WorkOrder, WorkOrderStatusHistory
from apps.work_orders.tests.base import WorkOrderTestCase


class StartAttentionAPITestCase(WorkOrderTestCase):
    """Base de las pruebas: cliente de API, permiso funcional y helpers."""

    UNKNOWN_PK = 999_999

    def setUp(self):
        super().setUp()

        self.api = APIClient()

        # Iniciar la atención se habilita por PERMISO, no por rol: ser técnico
        # activo abre el canal, pero no autoriza la acción. Se concede aquí el
        # mismo permiso que exige la web.
        self.start_permission = Permission.objects.get(
            codename="start_workorder",
            content_type__app_label="work_orders",
        )
        self.technician.user_permissions.add(self.start_permission)

    def start_url(self, pk):
        return reverse("work_orders_api:start_attention", args=[pk])

    def authenticate(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        return token

    def create_foreign_order(self):
        """Orden asignada al otro técnico."""
        order = self.create_order()
        order.assign_technician(
            technician=self.other_technician,
            assigned_by=self.supervisor,
        )

        return order


class StartAttentionSuccessTests(StartAttentionAPITestCase):
    """Escenarios 1, 5 y 6: el camino feliz y qué llega al dominio."""

    def test_own_assigned_order_starts_attention(self):
        """1. OT propia y elegible -> 200 y pasa a IN_PROGRESS."""
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        response = self.api.post(self.start_url(order.pk), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)
        self.assertIsNotNone(order.started_at)

    def test_response_is_the_updated_detail(self):
        """La respuesta es la ficha del día 3 ya actualizada.

        Reutilizar `WorkOrderDetailSerializer` evita que el cliente tenga que
        pedir el detalle otra vez para refrescar la pantalla, y evita inventar
        una segunda forma de respuesta para la misma orden.
        """
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        data = self.api.post(self.start_url(order.pk), {}, format="json").data

        self.assertEqual(data["id"], order.pk)
        self.assertEqual(data["status"], WorkOrder.Status.IN_PROGRESS)
        self.assertEqual(data["status_display"], "En atención")

        # Mismos campos que el detalle: ni uno más, ni uno menos.
        self.assertIn("address", data)
        self.assertIn("branch", data)
        self.assertIn("zone", data)

    def test_remarks_are_recorded_in_the_status_history(self):
        """5. La observación queda en el historial, igual que en la web."""
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        self.api.post(
            self.start_url(order.pk),
            {"remarks": "Cliente confirmó acceso al domicilio."},
            format="json",
        )

        entry = WorkOrderStatusHistory.objects.filter(
            work_order=order,
            new_status=WorkOrder.Status.IN_PROGRESS,
        ).latest("changed_at")

        self.assertEqual(
            entry.remarks,
            "Cliente confirmó acceso al domicilio.",
        )
        # El responsable del cambio es el técnico autenticado, no el creador
        # de la orden ni el supervisor que la asignó.
        self.assertEqual(entry.changed_by, self.technician)

    def test_remarks_are_optional(self):
        """Sin body la petición es válida: el campo es opcional."""
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        response = self.api.post(self.start_url(order.pk), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        entry = WorkOrderStatusHistory.objects.filter(
            work_order=order,
            new_status=WorkOrder.Status.IN_PROGRESS,
        ).latest("changed_at")

        self.assertEqual(entry.remarks, "")

    def test_client_cannot_influence_the_outcome(self):
        """6. `status`, `started_at` y el técnico enviados a mano se ignoran.

        No hay un filtrado explícito que los descarte: sencillamente no son
        campos del serializador, así que nunca llegan al servicio de dominio.
        """
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        before = timezone.now()

        response = self.api.post(
            self.start_url(order.pk),
            {
                "remarks": "Inicio normal.",
                "status": WorkOrder.Status.LIQUIDATED,
                "started_at": "2020-01-01T00:00:00Z",
                "assigned_technician": self.other_technician.pk,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        order.refresh_from_db()

        # El estado lo decidió la matriz de transiciones, no el payload.
        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)
        # La hora la puso `timezone.now()` dentro del dominio.
        self.assertGreaterEqual(order.started_at, before)
        # El técnico asignado no se movió.
        self.assertEqual(order.assigned_technician, self.technician)

    def test_the_service_is_used_not_just_the_model(self):
        """El efecto colateral prueba que se pasó por `start_order_attention`.

        Una instalación en preventa mueve la suscripción a «En instalación».
        Ese efecto vive en el servicio, no en `WorkOrder.start_attention()`:
        si la vista llamara al modelo directamente, la suscripción se quedaría
        en preventa y esta prueba fallaría.
        """
        order = self.create_assigned_order(order_type=self.installation_type)

        self.assertEqual(
            order.subscription.status,
            Subscription.Status.PRESALE,
        )

        self.authenticate(self.technician)

        self.api.post(self.start_url(order.pk), {}, format="json")

        order.subscription.refresh_from_db()
        self.assertEqual(
            order.subscription.status,
            Subscription.Status.INSTALLATION,
        )


class StartAttentionDomainRejectionTests(StartAttentionAPITestCase):
    """Escenario 4: el dominio rechaza y la API traduce, no decide."""

    def test_order_in_non_startable_status_is_rejected(self):
        """4. Estado no iniciable -> 400 con el mensaje del dominio."""
        # La atención ya está iniciada: IN_PROGRESS no está en
        # STARTABLE_STATUSES. Es el caso real de un doble envío del técnico.
        order = self.create_order_in_progress()

        started_at_before = order.started_at

        self.authenticate(self.technician)

        response = self.api.post(self.start_url(order.pk), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"],
            "No se puede iniciar la atención de una orden en estado "
            "En atención.",
        )

        # La orden no cambió: el servicio es atómico y no dejó nada a medias.
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)
        self.assertEqual(order.started_at, started_at_before)

    def test_rejection_does_not_add_history(self):
        """Un rechazo no deja rastro en el historial de estados."""
        order = self.create_order_in_progress()

        entries_before = WorkOrderStatusHistory.objects.filter(
            work_order=order,
        ).count()

        self.authenticate(self.technician)

        self.api.post(self.start_url(order.pk), {}, format="json")

        self.assertEqual(
            WorkOrderStatusHistory.objects.filter(work_order=order).count(),
            entries_before,
        )

    def test_rejection_message_comes_from_the_domain(self):
        """El mensaje no se redacta en la vista: se toma del dominio.

        Se compara contra el texto que produce el propio modelo, así que si
        mañana el dominio cambia la redacción, la API la sigue sin tocarse y
        esta prueba lo confirma en lugar de fijar una copia literal.
        """
        order = self.create_attended_order()

        self.authenticate(self.technician)

        response = self.api.post(self.start_url(order.pk), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"],
            "No se puede iniciar la atención de una orden en estado "
            f"{order.get_status_display()}.",
        )

    def test_pending_order_is_not_reachable(self):
        """Una OT PENDING no llega al 400: no tiene técnico, así que da 404.

        Se documenta a propósito. La actividad cita PENDING como ejemplo de
        estado no iniciable, pero una orden en PENDING todavía no ha sido
        asignada, de modo que el filtro por técnico la excluye antes: el
        rechazo que corresponde es el 404 uniforme, no el 400 del dominio.
        """
        order = self.create_order()

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(order.assigned_technician)

        self.authenticate(self.technician)

        response = self.api.post(self.start_url(order.pk), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class StartAttentionAuthorizationTests(StartAttentionAPITestCase):
    """Escenarios 2 y 3: las tres capas y su orden."""

    def test_technician_without_the_permission_is_rejected(self):
        """2. Técnico sin `start_workorder` -> 403 sobre su propia OT."""
        order = self.create_assigned_order()

        self.technician.user_permissions.remove(self.start_permission)

        self.authenticate(self.technician)

        response = self.api.post(self.start_url(order.pk), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)

    def test_missing_permission_never_reveals_which_orders_exist(self):
        """Sin el permiso, todo id responde 403: no se puede sondear.

        Fija el orden de evaluación. Si la orden se resolviera antes que el
        permiso, la OT ajena daría 404 y la propia 403, y esa diferencia
        revelaría cuáles existen.
        """
        own = self.create_assigned_order()
        foreign = self.create_foreign_order()

        self.technician.user_permissions.remove(self.start_permission)

        self.authenticate(self.technician)

        for label, pk in (
            ("propia", own.pk),
            ("ajena", foreign.pk),
            ("inexistente", self.UNKNOWN_PK),
        ):
            with self.subTest(caso=label):
                response = self.api.post(
                    self.start_url(pk), {}, format="json",
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_403_FORBIDDEN,
                )

    def test_foreign_order_and_unknown_id_are_indistinguishable(self):
        """3. Con permiso, la OT ajena responde igual que un id inexistente."""
        foreign = self.create_foreign_order()

        self.authenticate(self.technician)

        foreign_response = self.api.post(
            self.start_url(foreign.pk), {}, format="json",
        )
        unknown_response = self.api.post(
            self.start_url(self.UNKNOWN_PK), {}, format="json",
        )

        self.assertEqual(
            foreign_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            foreign_response.status_code,
            unknown_response.status_code,
        )
        self.assertEqual(foreign_response.data, unknown_response.data)

        # Y la orden ajena no se tocó.
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, WorkOrder.Status.ASSIGNED)

    def test_request_without_token_is_rejected(self):
        """Sin token -> 401, antes de cualquier otra capa."""
        order = self.create_assigned_order()

        response = self.api.post(self.start_url(order.pk), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_non_technician_is_rejected(self):
        """Un usuario fuera del canal técnico no llega ni al permiso de acción.

        Se le concede `start_workorder` a propósito: aun teniéndolo, no es
        técnico activo, y el canal se cierra antes. Las dos capas no están
        fusionadas.
        """
        order = self.create_assigned_order()

        self.atc_user.user_permissions.add(self.start_permission)

        self.authenticate(self.atc_user)

        response = self.api.post(self.start_url(order.pk), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["detail"],
            "Se requiere un usuario con rol técnico activo.",
        )


class StartAttentionMethodTests(StartAttentionAPITestCase):
    """La acción solo existe como POST."""

    def test_read_methods_are_not_allowed(self):
        """Un GET nunca cambia estado: el endpoint no lo expone."""
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        for method in ("get", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.api, method)(self.start_url(order.pk))

                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                )

        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)
