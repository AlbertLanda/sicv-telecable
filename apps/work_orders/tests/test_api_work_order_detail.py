"""
Pruebas del endpoint de detalle de una orden de trabajo del técnico.

Cubren los escenarios de la actividad: OT propia, OT de otro técnico, id
inexistente, sin token y usuario autenticado sin rol técnico. El caso central
no es que la OT ajena responda 404, sino que responda **exactamente lo mismo**
que un id inexistente: si las dos respuestas difirieran en algo, el endpoint
permitiría enumerar órdenes ajenas.

Se apoyan en `WorkOrderTestCase`, que ya construye sede, zona, cliente,
dirección, suscripción, catálogos y los usuarios `technician`,
`other_technician` y `atc_user`.
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.work_orders.tests.base import WorkOrderTestCase


class WorkOrderDetailAPITestCase(WorkOrderTestCase):
    """Base de las pruebas del endpoint: cliente de API y helpers."""

    # Id que no corresponde a ninguna orden. No se borra una orden creada
    # para obtenerlo: `WorkOrder` tiene relaciones PROTECT y el borrado no es
    # una operación del dominio.
    UNKNOWN_PK = 999_999

    def setUp(self):
        super().setUp()

        self.api = APIClient()

    def detail_url(self, pk):
        return reverse("work_orders_api:my_order_detail", args=[pk])

    def authenticate(self, user):
        """Autentica el cliente de API con el token del usuario indicado."""
        token, _ = Token.objects.get_or_create(user=user)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        return token

    def create_foreign_order(self):
        """Crea una orden asignada al otro técnico."""
        order = self.create_order()
        order.assign_technician(
            technician=self.other_technician,
            assigned_by=self.supervisor,
        )

        return order


class WorkOrderDetailContentTests(WorkOrderDetailAPITestCase):
    """Escenario 1: qué ve el técnico en su propia orden."""

    def test_technician_gets_detail_of_own_order(self):
        """1. OT propia -> 200 con los campos de detalle."""
        order = self.create_assigned_order(
            detail="El cliente reporta intermitencia desde el lunes.",
        )

        self.authenticate(self.technician)

        response = self.api.get(self.detail_url(order.pk))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], order.pk)
        self.assertEqual(response.data["order_number"], order.order_number)
        self.assertEqual(
            response.data["detail"],
            "El cliente reporta intermitencia desde el lunes.",
        )
        self.assertEqual(response.data["branch"], "Sede Central")
        self.assertEqual(response.data["zone"], "Zona Norte")
        self.assertIsNotNone(response.data["created_at"])

    def test_detail_exposes_the_agreed_fields(self):
        """La ficha trae los campos de la lista más los del detalle.

        La comparación es contra el conjunto exacto: si alguien agrega un
        campo sin decidirlo, la prueba falla en vez de dejarlo pasar.
        """
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        data = self.api.get(self.detail_url(order.pk)).data

        self.assertEqual(
            set(data.keys()),
            {
                # Heredados de la fila del listado.
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
                # Propios del detalle.
                "address",
                "detail",
                "branch",
                "zone",
            },
        )

    def test_detail_keeps_the_list_criteria_for_choices(self):
        """Los choices heredados siguen viajando con código y etiqueta."""
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        data = self.api.get(self.detail_url(order.pk)).data

        self.assertEqual(data["status"], order.status)
        self.assertEqual(data["status_display"], "Asignada")
        self.assertEqual(data["priority"], order.priority)
        self.assertEqual(data["priority_display"], "Normal")

    def test_detail_exposes_the_attention_address(self):
        """La dirección de atención sale de la suscripción, sin la ficha completa."""
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        address = self.api.get(self.detail_url(order.pk)).data["address"]

        self.assertEqual(
            set(address.keys()),
            {
                "address",
                "reference",
                "district",
                "latitude",
                "longitude",
                "gps_link",
            },
        )
        self.assertEqual(address["address"], "Av. Los Álamos 123")
        self.assertEqual(address["district"], "Chachapoyas")

    def test_detail_shows_the_customer_block_of_the_list(self):
        """El bloque de cliente se hereda tal cual, sin duplicar la definición."""
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        customer = self.api.get(self.detail_url(order.pk)).data["customer"]

        self.assertEqual(
            set(customer.keys()),
            {"code", "document_type", "document_number", "display_name"},
        )
        self.assertEqual(customer["display_name"], "Juan Pérez Ramos")

    def test_order_without_zone_is_serialized_as_null(self):
        """La zona es opcional en el modelo: sin ella la ficha responde igual."""
        order = self.create_assigned_order(zone=None)

        self.authenticate(self.technician)

        response = self.api.get(self.detail_url(order.pk))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["zone"])


class WorkOrderDetailIsolationTests(WorkOrderDetailAPITestCase):
    """Escenarios 2 y 3: no se puede distinguir lo ajeno de lo inexistente."""

    def test_detail_of_another_technicians_order_is_not_found(self):
        """2. OT de otro técnico -> 404, nunca 403."""
        order = self.create_foreign_order()

        self.authenticate(self.technician)

        response = self.api.get(self.detail_url(order.pk))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_id_is_not_found(self):
        """3. Id inexistente -> 404."""
        self.authenticate(self.technician)

        response = self.api.get(self.detail_url(self.UNKNOWN_PK))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_foreign_order_and_unknown_id_are_indistinguishable(self):
        """Criterio de aceptación: las dos respuestas son idénticas.

        Mismo código y mismo cuerpo. Si mañana alguien agrega un mensaje del
        tipo «no tienes acceso a esta orden», esta prueba lo detiene: ese
        mensaje confirmaría que la orden existe.
        """
        foreign = self.create_foreign_order()

        self.authenticate(self.technician)

        foreign_response = self.api.get(self.detail_url(foreign.pk))
        unknown_response = self.api.get(self.detail_url(self.UNKNOWN_PK))

        self.assertEqual(
            foreign_response.status_code,
            unknown_response.status_code,
        )
        self.assertEqual(foreign_response.data, unknown_response.data)

    def test_not_found_message_is_the_project_standard(self):
        """El 404 usa el mensaje de DRF en español, no el de Django.

        Django responde «No WorkOrder matches the given query.»: en inglés y
        nombrando el modelo interno. La vista lo sustituye por el 404 estándar
        del proyecto. No distingue los dos casos —es el mismo mensaje para la
        orden ajena y para la inexistente—, solo deja de contar de más.
        """
        foreign = self.create_foreign_order()

        self.authenticate(self.technician)

        for label, pk in (("ajena", foreign.pk), ("inexistente", self.UNKNOWN_PK)):
            with self.subTest(caso=label):
                response = self.api.get(self.detail_url(pk))

                self.assertEqual(response.data, {"detail": "No encontrado."})

    def test_unassigned_order_is_not_found(self):
        """Una OT sin técnico asignado tampoco es visible para nadie."""
        order = self.create_order()

        self.authenticate(self.technician)

        response = self.api.get(self.detail_url(order.pk))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class WorkOrderDetailPermissionTests(WorkOrderDetailAPITestCase):
    """Escenarios 4 y 5: quién puede usar el endpoint."""

    def test_request_without_token_is_rejected(self):
        """4. Sin token -> 401."""
        order = self.create_assigned_order()

        response = self.api.get(self.detail_url(order.pk))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_non_technician_is_rejected(self):
        """5. Usuario autenticado sin rol técnico -> 403 por el permiso."""
        order = self.create_assigned_order()

        self.authenticate(self.atc_user)

        response = self.api.get(self.detail_url(order.pk))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_permission_is_evaluated_before_the_object(self):
        """El no técnico recibe 403 incluso apuntando a un id inexistente.

        Confirma el orden de evaluación: el permiso de canal decide antes de
        que se intente resolver la orden. El 403 informa sobre el usuario, no
        sobre la existencia de la OT.
        """
        self.authenticate(self.atc_user)

        response = self.api.get(self.detail_url(self.UNKNOWN_PK))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_technician_moved_to_another_role_loses_access(self):
        """Un cambio de rol posterior al login revoca el acceso al detalle."""
        order = self.create_assigned_order()

        self.authenticate(self.technician)
        self.assertEqual(
            self.api.get(self.detail_url(order.pk)).status_code,
            status.HTTP_200_OK,
        )

        self.technician.role = self.technician.Role.ATC
        self.technician.save(update_fields=["role"])

        response = self.api.get(self.detail_url(order.pk))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class WorkOrderDetailReadOnlyTests(WorkOrderDetailAPITestCase):
    """El detalle no abre ninguna puerta de escritura."""

    def test_write_methods_are_not_allowed(self):
        """Ninguna acción de transición es alcanzable desde este endpoint."""
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        url = self.detail_url(order.pk)

        for method in ("post", "patch", "put", "delete"):
            with self.subTest(method=method):
                response = getattr(self.api, method)(url)

                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                )
