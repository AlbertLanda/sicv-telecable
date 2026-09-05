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

from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.services.models import PlanTariff
from apps.work_orders.services import attend_order, liquidate_order
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
                "plan_details",
                "detail",
                "branch",
                "zone",
                "reason",
                "started_at",
                "attended_at",
                "can_start_attention",
                "technical_data",
            },
        )

    def test_plan_details_publishes_what_the_field_work_needs(self):
        """El bloque del plan trae lo que decide el trabajo en campo.

        Velocidad, tecnología y puntos de TV incluidos son lo que el técnico
        necesita **antes** de cablear: qué equipo instala, cómo lo configura y
        cuántas salidas entran sin cargo.
        """
        order = self.create_assigned_order()

        self.authenticate(self.technician)

        plan = self.api.get(self.detail_url(order.pk)).data["plan_details"]

        self.assertEqual(plan["code"], "PLAN100")
        self.assertEqual(plan["name"], "Fibra 100 Mbps")
        self.assertEqual(plan["service_type"], "Internet")
        self.assertEqual(plan["speed_mbps"], 100)
        self.assertEqual(plan["monthly_price"], "80.00")

    def test_plan_details_serves_null_tariff_instead_of_zeros(self):
        """Sin tarifa aplicada el bloque es `null`, no ceros.

        «Sin tarifa geográfica» y «tarifa de cero soles» son estados
        distintos. Un bloque de ceros los volvería indistinguibles, que es el
        mismo criterio con el que `technical_data` distingue «aún no liquidó»
        de «liquidó dejando campos en blanco».
        """
        order = self.create_assigned_order()

        self.assertIsNone(order.subscription.tariff)

        self.authenticate(self.technician)

        plan = self.api.get(self.detail_url(order.pk)).data["plan_details"]

        self.assertIsNone(plan["tariff"])

    def test_plan_details_reports_granted_courtesies_and_annexes(self):
        self.service_type.supports_tv_annexes = True
        self.service_type.annex_monthly_price = Decimal("5.00")
        self.service_type.save()
        self.plan.included_tv_points = 2
        self.plan.save()
        order = self.create_assigned_order()
        self.authenticate(self.technician)

        for granted, annexes, total in ((1, 0, 1), (1, 1, 2), (2, 3, 5)):
            with self.subTest(granted=granted, annexes=annexes):
                self.subscription.initial_tv_courtesy_granted = granted
                self.subscription.annex_count = annexes
                self.subscription.save()
                details = self.api.get(self.detail_url(order.pk)).data["plan_details"]
                self.assertEqual(details["included_tv_points"], granted)
                self.assertEqual(details["annex_count"], annexes)
                self.assertEqual(details["total_tv_points"], total)

    def test_contract_prices_survive_catalog_changes_and_include_annexes(self):
        self.service_type.supports_tv_annexes = True
        self.service_type.annex_monthly_price = Decimal("5.00")
        self.service_type.save()
        tariff = PlanTariff.objects.create(
            plan=self.plan, branch=self.branch,
            installation_fee=Decimal("90.00"), monthly_fee=Decimal("85.00"),
        )
        self.subscription.tariff = tariff
        self.subscription.base_installation_fee = Decimal("50.00")
        self.subscription.base_monthly_fee = Decimal("50.00")
        self.subscription.annex_count = 3
        self.subscription.save()
        order = self.create_assigned_order()
        self.authenticate(self.technician)

        for applied_tariff in (tariff, None):
            with self.subTest(tariff=applied_tariff):
                self.subscription.tariff = applied_tariff
                self.subscription.save(update_fields=["tariff"])
                details = self.api.get(self.detail_url(order.pk)).data["plan_details"]
                self.assertEqual(details["base_installation_fee"], "50.00")
                self.assertEqual(details["base_monthly_fee"], "50.00")
                self.assertEqual(details["annex_monthly_charge"], "15.00")
                self.assertEqual(details["total_monthly_price"], "65.00")

    def test_free_contracted_installation_is_reported_as_zero_without_tariff(self):
        order = self.create_assigned_order()
        self.authenticate(self.technician)
        details = self.api.get(self.detail_url(order.pk)).data["plan_details"]
        self.assertEqual(details["base_installation_fee"], "0.00")

    def test_plan_details_publishes_the_applied_tariff_when_there_is_one(self):
        """Con tarifa, viaja el importe real y dónde se aplica.

        `monthly_price` es el precio referencial del catálogo y
        `tariff.monthly_fee` lo que se cobra en esa sede. Viajan los dos y con
        valores distintos a propósito: si el serializador confundiera uno con
        otro, esta prueba lo detecta.
        """
        tariff = PlanTariff.objects.create(
            plan=self.plan,
            branch=self.branch,
            installation_fee=Decimal("150.00"),
            monthly_fee=Decimal("95.00"),
        )

        self.subscription.tariff = tariff
        self.subscription.save(update_fields=["tariff"])

        order = self.create_assigned_order()

        self.authenticate(self.technician)

        plan = self.api.get(self.detail_url(order.pk)).data["plan_details"]

        self.assertEqual(plan["monthly_price"], "80.00")
        self.assertEqual(plan["tariff"]["monthly_fee"], "95.00")
        self.assertEqual(plan["tariff"]["installation_fee"], "150.00")
        self.assertEqual(plan["tariff"]["branch"], self.branch.name)
        self.assertIsNone(plan["tariff"]["zone"])

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

    def test_detail_exposes_the_work_fields_of_the_technician(self):
        """La ficha dice por qué existe la OT, cuándo se trabajó y qué ofrecer.

        `reason` es catálogo y puede faltar; `started_at` y `attended_at` son
        nulos mientras no ocurran; `can_start_attention` lo decide el dominio
        —no la app— leyendo las mismas condiciones que verifica
        `start_attention()`.
        """
        order = self.create_assigned_order(reason=self.installation_reason)

        self.authenticate(self.technician)

        data = self.api.get(self.detail_url(order.pk)).data

        self.assertEqual(data["reason"], "Cliente nuevo")
        self.assertIsNone(data["started_at"])
        self.assertIsNone(data["attended_at"])
        self.assertTrue(data["can_start_attention"])

    def test_started_order_reports_its_timestamps(self):
        """Con la atención iniciada, la marca de tiempo viaja y la acción no.

        Una orden ya en atención no vuelve a iniciarse: `can_start_attention`
        pasa a `False` sin que la app tenga que deducirlo del estado.
        """
        order = self.create_order_in_progress()

        self.authenticate(self.technician)

        data = self.api.get(self.detail_url(order.pk)).data

        self.assertIsNotNone(data["started_at"])
        self.assertFalse(data["can_start_attention"])


class WorkOrderDetailLocationTests(WorkOrderDetailAPITestCase):
    """Ubicación: la dirección textual siempre; el GPS solo si es real.

    La regla vive en `apps.customers.coordinates` y estas pruebas verifican que
    el canal técnico la aplique. El caso que las motiva no es teórico:
    Distriluz responde `0` en `gpsx`/`gpsy` cuando el suministro no tiene
    georreferencia, y `0,0` es un punto en el golfo de Guinea. Un técnico que
    abre ese enlace en la puerta del cliente no ve un dato faltante: ve un
    destino equivocado.
    """

    def setUp(self):
        super().setUp()
        self.authenticate(self.technician)

    def location_of(self, **address_fields):
        """Bloque `address` de la ficha, con la dirección ajustada."""
        for field, value in address_fields.items():
            setattr(self.address, field, value)

        self.address.save()

        order = self.create_assigned_order()

        return self.api.get(self.detail_url(order.pk)).data["address"]

    def test_valid_coordinates_travel_with_their_map_link(self):
        """Con GPS real, el técnico recibe las coordenadas y el enlace."""
        location = self.location_of(
            latitude="-6.2290000",
            longitude="-77.8730000",
        )

        self.assertEqual(location["latitude"], "-6.2290000")
        self.assertEqual(location["longitude"], "-77.8730000")
        self.assertIn("-6.2290000,-77.8730000", location["gps_link"])

    def test_zero_coordinates_are_not_gps(self):
        """`0 / 0.0000000` es el centinela de «sin dato», no una ubicación.

        Es el caso exacto que la coordinación de hoy pide blindar. Se publica
        `null` y sin enlace: el técnico ve que no hay GPS, en lugar de recibir
        un pin a 9.000 km.
        """
        location = self.location_of(
            latitude="0.0000000",
            longitude="0.0000000",
        )

        self.assertIsNone(location["latitude"])
        self.assertIsNone(location["longitude"])
        self.assertEqual(location["gps_link"], "")

    def test_empty_coordinates_are_not_gps(self):
        """Sin coordenadas registradas, el bloque responde igual: `null`."""
        location = self.location_of(latitude=None, longitude=None)

        self.assertIsNone(location["latitude"])
        self.assertIsNone(location["longitude"])
        self.assertEqual(location["gps_link"], "")

    def test_half_a_coordinate_is_not_published(self):
        """El par es indivisible: una coordenada sola no ubica nada.

        Publicar la mitad invitaría a que alguien compusiera un mapa con el
        valor que falta puesto a cero, que es el mismo problema por otra vía.
        """
        location = self.location_of(latitude="-6.2290000", longitude="0")

        self.assertIsNone(location["latitude"])
        self.assertIsNone(location["longitude"])
        self.assertEqual(location["gps_link"], "")

    def test_the_textual_address_always_travels(self):
        """Sin GPS, la dirección y el distrito siguen ahí.

        Es lo que permite llegar cuando el GPS falta, y la razón por la que
        descartar coordenadas falsas no deja al técnico sin nada: la ubicación
        útil nunca fue la coordenada.
        """
        location = self.location_of(
            latitude="0",
            longitude="0",
            reference="Frente al parque, portón azul",
        )

        self.assertEqual(location["address"], "Av. Los Álamos 123")
        self.assertEqual(location["district"], "Chachapoyas")
        self.assertEqual(
            location["reference"],
            "Frente al parque, portón azul",
        )

    def test_a_stored_link_over_invalid_coordinates_is_not_served(self):
        """Un enlace guardado antes de la regla no se publica.

        El enlace se **deriva** de las coordenadas en lugar de leerse de la
        base de datos, justamente porque el que hay almacenado pudo
        construirse sobre un `0,0`. Si se sirviera tal cual, el dato falso
        volvería a aparecer por la puerta de atrás.
        """
        location = self.location_of(
            latitude="0",
            longitude="0",
            gps_link=(
                "https://www.google.com/maps/search/?api=1&query=0.0,0.0"
            ),
        )

        self.assertEqual(location["gps_link"], "")


class WorkOrderDetailTechnicalDataTests(WorkOrderDetailAPITestCase):
    """El bloque de datos técnicos: una sola OT, sin modelo paralelo."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.technician)

    def test_order_without_liquidation_reports_null(self):
        """Sin nada registrado, `technical_data` es `null`.

        `null` y no un bloque de campos vacíos: el cliente debe poder
        distinguir «el técnico aún no liquidó» de «liquidó dejando los campos
        opcionales en blanco».
        """
        order = self.create_assigned_order()

        data = self.api.get(self.detail_url(order.pk)).data

        self.assertIsNone(data["technical_data"])

    def test_registered_technical_data_travels_in_the_detail(self):
        """Lo que el técnico ejecutó se lee en la misma ficha.

        Los datos salen de `WorkOrderLiquidation`, que es donde el dominio ya
        los guarda: la Orden Técnica sigue siendo una sola `WorkOrder` y este
        bloque no es una copia paralela.
        """
        liquidation = self.create_liquidation()

        data = self.api.get(self.detail_url(liquidation.work_order.pk)).data

        technical_data = data["technical_data"]

        self.assertEqual(
            set(technical_data.keys()),
            {
                "liquidated_at",
                "resolution_detail",
                "technical_notes",
                "network_element",
                "network_port",
                "equipment_serial",
                "signal_level_dbm",
                "cable_meters_used",
                "krill_reference",
                "review_status",
                "review_status_display",
            },
        )

        self.assertEqual(technical_data["network_element"], "NAP-014")
        self.assertEqual(technical_data["network_port"], "5")
        self.assertEqual(technical_data["equipment_serial"], "ABC123")
        self.assertEqual(
            technical_data["review_status"],
            "LIQUIDATED",
        )
        self.assertEqual(
            technical_data["review_status_display"],
            "Liquidada",
        )

    def test_technical_data_is_read_only_in_this_channel(self):
        """El detalle no admite escritura, tampoco de los datos técnicos.

        Registrarlos pasa por `liquidate_order()`, que exige orden atendida y
        aplica el ciclo de revisión. Una escritura aquí sería una segunda vía
        de liquidación sin revisión.
        """
        liquidation = self.create_liquidation()

        url = self.detail_url(liquidation.work_order.pk)

        for method in ("put", "patch"):
            with self.subTest(metodo=method):
                response = getattr(self.api, method)(
                    url,
                    {"technical_data": {"equipment_serial": "HACKED"}},
                    format="json",
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                )

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.equipment_serial, "ABC123")

    def test_another_technicians_technical_data_is_unreachable(self):
        """Aislamiento por usuario: el bloque técnico no abre una vía nueva.

        La ficha completa —datos técnicos incluidos— vive detrás del mismo
        queryset filtrado por `request.user`, así que una OT ajena responde 404
        y lo que otro técnico registró en campo no viaja en ninguna forma.
        """
        foreign_order = self.create_order()
        foreign_order.assign_technician(
            technician=self.other_technician,
            assigned_by=self.supervisor,
        )
        foreign_order.start_attention(user=self.other_technician)

        attend_order(
            foreign_order,
            result=self.installation_success,
            user=self.other_technician,
        )

        liquidate_order(
            foreign_order,
            user=self.other_technician,
            resolution_detail="Instalación del otro técnico.",
            equipment_serial="SERIE-AJENA",
        )

        response = self.api.get(self.detail_url(foreign_order.pk))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn("SERIE-AJENA", response.content.decode())


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
