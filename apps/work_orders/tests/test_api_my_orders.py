"""
Pruebas del endpoint «Mis órdenes» de la API del técnico.

Cubren los seis escenarios de la actividad: técnico con y sin órdenes,
aislamiento frente a las órdenes de otro técnico, rechazo del usuario
autenticado sin rol técnico, rechazo sin token y ausencia de N+1.

Se apoyan en `WorkOrderTestCase`, que ya construye sede, cliente,
suscripción, catálogos y los usuarios `technician`, `other_technician`,
`inactive_technician` y `atc_user`.
"""

from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.work_orders.tests.base import WorkOrderTestCase


class MyWorkOrdersAPITestCase(WorkOrderTestCase):
    """Base de las pruebas del endpoint: cliente de API y helpers de token."""

    def setUp(self):
        super().setUp()

        self.url = reverse("work_orders_api:my_orders")
        self.api = APIClient()

    def authenticate(self, user):
        """Autentica el cliente de API con el token del usuario indicado."""
        token, _ = Token.objects.get_or_create(user=user)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        return token

    def order_numbers(self, response):
        return [row["order_number"] for row in response.data]


class MyWorkOrdersListTests(MyWorkOrdersAPITestCase):
    """Escenarios 1 a 3: qué ve el técnico autenticado."""

    def test_technician_sees_only_own_orders(self):
        """1 y 3. Solo sus propias OT; la de otro técnico no aparece."""
        own = self.create_assigned_order()

        other = self.create_order()
        other.assign_technician(
            technician=self.other_technician,
            assigned_by=self.supervisor,
        )

        # Una orden sin técnico asignado tampoco debe aparecer.
        unassigned = self.create_order()

        self.authenticate(self.technician)

        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.order_numbers(response), [own.order_number])
        self.assertNotIn(other.order_number, self.order_numbers(response))
        self.assertNotIn(unassigned.order_number, self.order_numbers(response))

    def test_technician_without_orders_gets_empty_list(self):
        """2. Técnico sin OT asignadas -> 200 con lista vacía."""
        # La orden existe, pero es de otro técnico.
        order = self.create_order()
        order.assign_technician(
            technician=self.other_technician,
            assigned_by=self.supervisor,
        )

        self.authenticate(self.technician)

        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_response_exposes_the_agreed_fields(self):
        """La fila trae los campos mínimos acordados y nada operativo."""
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        row = self.api.get(self.url).data[0]

        self.assertEqual(
            set(row.keys()),
            {
                "id",
                "order_number",
                "customer",
                "service_type",
                "plan",
                "order_type",
                "subtype",
                "status",
                "status_display",
                "priority",
                "priority_display",
                "scheduled_at",
                "created_at",
            },
        )

        self.assertEqual(row["order_number"], order.order_number)
        self.assertEqual(row["status"], order.status)
        self.assertEqual(row["status_display"], "Asignada")
        self.assertEqual(row["order_type"], "Instalación")
        self.assertEqual(row["service_type"], "Internet")

        # Identificación básica del cliente, sin el resto de la ficha.
        self.assertEqual(
            set(row["customer"].keys()),
            {"code", "document_type", "document_number", "display_name"},
        )
        self.assertEqual(row["customer"]["code"], "CLI001")
        self.assertEqual(row["customer"]["display_name"], "Juan Pérez Ramos")

    def test_orders_are_sorted_by_schedule_with_nulls_last(self):
        """El orden es por fecha programada; las sin fecha van al final."""
        now = timezone.now()

        later = self.create_assigned_order(
            scheduled_at=now + timedelta(hours=5),
        )
        sooner = self.create_assigned_order(
            scheduled_at=now + timedelta(hours=1),
        )
        unscheduled = self.create_assigned_order()

        self.authenticate(self.technician)

        response = self.api.get(self.url)

        self.assertEqual(
            self.order_numbers(response),
            [
                sooner.order_number,
                later.order_number,
                unscheduled.order_number,
            ],
        )


class MyWorkOrdersPermissionTests(MyWorkOrdersAPITestCase):
    """Escenarios 4 y 5: quién puede usar el endpoint."""

    def test_request_without_token_is_rejected(self):
        """5. Sin token -> 401."""
        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_non_technician_is_rejected(self):
        """4. Usuario autenticado sin rol técnico -> 403 por el permiso."""
        self.authenticate(self.atc_user)

        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_deactivated_technician_with_live_token_is_rejected(self):
        """Un token vigente no sobrevive a la desactivación de su dueño.

        El token del canal técnico no caduca, así que el permiso debe
        reevaluar rol y estado en cada petición, no solo al emitirlo.
        """
        self.authenticate(self.technician)
        self.assertEqual(self.api.get(self.url).status_code, 200)

        self.technician.is_active = False
        self.technician.save(update_fields=["is_active"])

        response = self.api.get(self.url)

        # Sin usuario activo la autenticación por token ya no resuelve: DRF
        # responde 401 antes de llegar al permiso de rol.
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_technician_moved_to_another_role_loses_access(self):
        """Un cambio de rol posterior al login revoca el acceso."""
        self.authenticate(self.technician)
        self.assertEqual(self.api.get(self.url).status_code, 200)

        self.technician.role = self.technician.Role.ATC
        self.technician.save(update_fields=["role"])

        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class MyWorkOrdersQueryCountTests(MyWorkOrdersAPITestCase):
    """Escenario 6: el listado no crece en consultas con el número de OT."""

    def test_query_count_does_not_grow_with_the_number_of_orders(self):
        """Varias OT -> mismo número de consultas que con una sola.

        Se compara contra la línea base medida con una orden en lugar de
        fijar un número absoluto: lo que importa es que el costo no dependa
        del tamaño del listado. Si alguien quita un `select_related`, la
        segunda medición se dispara y la prueba falla.
        """
        self.authenticate(self.technician)

        self.create_assigned_order()

        with CaptureQueriesContext(connection) as baseline:
            self.api.get(self.url)

        for _ in range(6):
            self.create_assigned_order()

        with self.assertNumQueries(len(baseline.captured_queries)):
            response = self.api.get(self.url)

        self.assertEqual(len(response.data), 7)
