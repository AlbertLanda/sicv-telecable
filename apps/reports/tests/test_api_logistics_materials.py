"""Pruebas del feed de materiales para logística.

Mientras SICV no tenga datos migrados, **estas pruebas son la garantía de que
la integración funciona**. El sistema de logística está en producción y va a
programar contra el contrato que aquí se fija, así que lo que se comprueba no
es solo que el endpoint responda: es que responda *esto*, con estos nombres de
campo y estos códigos, porque cambiar cualquiera de los dos rompe un sistema
que no se despliega junto con este.

Cubren cuatro frentes:

1. **El contrato** — los campos que logística espera, con identificadores
   estables en vez de nombres.
2. **El acceso** — el feed es de quien tiene el permiso, no de cualquiera
   con un token.
3. **La fecha de logística** — el recorte por atención real, que es lo que
   hace que el cuadre semanal de mochila caiga en la semana correcta.
4. **La sincronización** — paginación, incremental y reconciliación de
   borrados.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.inventory.models import WorkOrderMaterialMovement
from apps.reports.materials import DATE_BASIS, DATE_BASIS_CHOICES
from apps.work_orders.models import (
    WorkOrder,
    WorkOrderFieldSheet,
    WorkOrderLiquidation,
)

from .test_material_report import MaterialReportTestCase


User = get_user_model()


LISTA = reverse("logistics_api:material_movements")
IDS = reverse("logistics_api:material_movement_ids")
WATERMARK = reverse("logistics_api:material_movement_watermark")


class LogisticsFeedTestCase(MaterialReportTestCase):
    """Reusa el escenario del reporte y le añade el cliente del canal.

    Es el mismo escenario a propósito: el feed y la hoja tienen que dar el
    mismo número, y compartir el montaje es lo que deja compararlos sin
    preguntarse si la diferencia viene de los datos.
    """

    def setUp(self):
        super().setUp()

        # El usuario de servicio del otro sistema. No es una persona y **no
        # tiene rol de almacén**: tiene el permiso, que es el criterio real.
        # Montarlo así en la prueba es lo que demuestra que el canal no exige
        # un rol concreto.
        self.service = User.objects.create_user(
            username="svc_logistica",
            password="test1234",
        )

        self.service.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="inventory",
                codename="view_workordermaterialmovement",
            )
        )

        self.token = Token.objects.create(user=self.service)

        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    # --- utilidades -------------------------------------------------------

    def attend(self, order, cuando):
        """Cierra la orden con una fecha de atención concreta.

        Se escribe con `update()` porque `attended_at` lo fija el propio flujo
        de la orden y aquí hace falta situarla en un día elegido.
        """
        WorkOrder.objects.filter(pk=order.pk).update(
            status=WorkOrder.Status.ATTENDED,
            attended_at=cuando,
        )
        order.refresh_from_db()

        return order

    def get(self, url=LISTA, **params):
        opciones = {
            "date_from": self.today.isoformat(),
            "date_to": self.today.isoformat(),
        }
        opciones.update({
            clave: valor for clave, valor in params.items() if valor is not None
        })

        return self.client.get(url, opciones)

    def rows(self, **params):
        respuesta = self.get(**params)
        self.assertEqual(respuesta.status_code, 200, respuesta.data)

        return respuesta.data["results"]


class ContractTests(LogisticsFeedTestCase):
    """Lo que logística va a leer del otro lado."""

    def test_row_carries_stable_identifiers(self):
        """Cada cosa que hay que cruzar viaja por su llave, no por su nombre.

        Es la prueba que sostiene el cuadre. Si el técnico o el material
        viajaran solo como texto, el primer homónimo o la primera tilde
        corregida en el admin desalinearían el cruce sin que nada fallara.
        """
        order = self.make_order(self.make_customer("CLI001"))
        self.add_material(order, self.utp, "45.50")
        self.attend(order, timezone.now())

        fila = self.rows()[0]

        self.assertEqual(fila["technician_id"], self.technician.pk)
        self.assertEqual(fila["material_code"], "UTP")
        self.assertEqual(fila["branch_code"], "SED01")
        self.assertEqual(fila["order_number"], order.order_number)
        self.assertEqual(fila["customer_code"], "CLI001")

        # El nombre viaja al lado, para poder leer el JSON, no para cruzar.
        self.assertEqual(fila["technician_name"], "Luis Quispe")
        self.assertEqual(fila["material_name"], "Cable UTP")

    def test_choices_travel_as_code_and_label(self):
        """El código es con lo que el otro sistema decide; la etiqueta, lo que pinta."""
        order = self.make_order(self.make_customer("CLI001"))
        self.add_material(
            order,
            self.decoder,
            "1.00",
            WorkOrderMaterialMovement.MovementType.REMOVED,
        )
        self.attend(order, timezone.now())

        fila = self.rows()[0]

        self.assertEqual(fila["movement_type"], "REMOVED")
        self.assertEqual(fila["movement_type_display"], "Retirado de domicilio")
        self.assertTrue(fila["is_removal"])
        self.assertEqual(fila["unit_of_measure"], "UNIT")
        self.assertEqual(fila["unit_of_measure_display"], "Unidad")

    def test_one_row_per_movement_not_per_order(self):
        """Igual que la hoja: instalar tres y retirar uno son cuatro filas."""
        order = self.make_order(self.make_customer("CLI001"))
        self.add_material(order, self.utp, "30.00")
        self.add_material(
            order,
            self.decoder,
            "1.00",
            WorkOrderMaterialMovement.MovementType.REMOVED,
        )
        self.attend(order, timezone.now())

        filas = self.rows()

        self.assertEqual(len(filas), 2)
        self.assertEqual({fila["order_number"] for fila in filas}, {order.order_number})

    def test_equipment_code_travels_for_recovered_gear(self):
        """Un equipo recuperado se recibe por su serie, no por su cantidad."""
        order = self.make_order(self.make_customer("CLI001"))
        WorkOrderFieldSheet.objects.create(
            work_order=order,
            equipment_code="AA:BB:CC:DD:EE:FF",
            updated_by=self.technician,
        )
        self.add_material(
            order,
            self.decoder,
            "1.00",
            WorkOrderMaterialMovement.MovementType.REMOVED,
        )
        self.attend(order, timezone.now())

        self.assertEqual(self.rows()[0]["equipment_code"], "AA:BB:CC:DD:EE:FF")

    def test_missing_field_sheet_is_empty_not_an_error(self):
        """La ficha es opcional; el material que salió del almacén no lo es."""
        order = self.make_order(self.make_customer("CLI001"))
        self.add_material(order, self.utp, "12.00")
        self.attend(order, timezone.now())

        self.assertEqual(self.rows()[0]["equipment_code"], "")

    def test_liquidation_state_travels_without_deciding_anything(self):
        """Viaja el estado, no la decisión de consolidar, que es de logística."""
        order = self.make_order(self.make_customer("CLI001"))
        self.add_material(order, self.utp, "12.00")
        self.attend(order, timezone.now())

        self.assertFalse(self.rows()[0]["is_liquidated"])
        self.assertEqual(self.rows()[0]["liquidation_status"], "")

        WorkOrderLiquidation.objects.create(
            work_order=order,
            liquidated_by=self.technician,
            liquidated_at=timezone.now(),
            resolution_detail="Instalación conforme.",
            review_status=WorkOrderLiquidation.ReviewStatus.VALIDATED,
        )

        fila = self.rows()[0]

        self.assertTrue(fila["is_liquidated"])
        self.assertEqual(fila["liquidation_status"], "VALIDATED")
        self.assertEqual(fila["liquidation_status_display"], "Validada")

    def test_feed_is_read_only(self):
        """El almacén lee consumo; no escribe en el dominio de campo."""
        for metodo in (self.client.post, self.client.put, self.client.delete):
            self.assertEqual(metodo(LISTA).status_code, 405)

    def test_date_basis_catalog_matches_the_domain(self):
        """Las opciones del formulario no son una copia que pueda desalinearse."""
        self.assertEqual(
            set(DATE_BASIS),
            {clave for clave, _etiqueta in DATE_BASIS_CHOICES},
        )


class AccessTests(LogisticsFeedTestCase):
    """El feed es de quien tiene el permiso, no de cualquiera con token."""

    def test_anonymous_is_rejected(self):
        self.assertEqual(APIClient().get(LISTA).status_code, 401)

    def test_token_without_permission_is_rejected(self):
        """Un token válido identifica; no autoriza.

        Importa porque los técnicos ya tienen token en producción: sin esta
        comprobación, cualquiera de ellos podría descargar el consumo de todos
        sus compañeros.
        """
        intruso = User.objects.create_user(
            username="otro", password="test1234"
        )
        cliente = APIClient()
        cliente.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=intruso).key}"
        )

        self.assertEqual(cliente.get(LISTA).status_code, 403)

    def test_permission_is_checked_on_every_request(self):
        """El token de DRF no caduca: retirar el permiso tiene que bastar."""
        self.assertEqual(self.get().status_code, 200)

        self.service.user_permissions.clear()
        self.service.refresh_from_db()

        self.assertEqual(self.get().status_code, 403)


class DateBasisTests(LogisticsFeedTestCase):
    """El recorte por atención real, que es la fecha del cuadre de mochila."""

    def test_defaults_to_attended_not_issued(self):
        """Una orden emitida el viernes y atendida el lunes cuenta el lunes.

        Es la diferencia que hace que el cuadre semanal cierre. Con el recorte
        por emisión, ese material aparecería en la semana en que ATC escribió
        la orden y no en la que salió de la mochila — y pasa todos los
        viernes, no es un caso de borde.
        """
        viernes = self.today - timedelta(days=3)
        lunes = self.today

        order = self.make_order(
            self.make_customer("CLI001"),
            issued_on=timezone.now() - timedelta(days=3),
        )
        self.add_material(order, self.utp, "30.00")
        self.attend(order, timezone.now())

        # La semana de la atención lo trae.
        self.assertEqual(
            len(self.rows(date_from=lunes.isoformat(), date_to=lunes.isoformat())),
            1,
        )

        # La de la emisión, no.
        self.assertEqual(
            len(self.rows(date_from=viernes.isoformat(), date_to=viernes.isoformat())),
            0,
        )

    def test_issued_basis_still_available(self):
        """El recorte del reporte sigue disponible, pidiéndolo."""
        order = self.make_order(
            self.make_customer("CLI001"),
            issued_on=timezone.now() - timedelta(days=3),
        )
        self.add_material(order, self.utp, "30.00")
        self.attend(order, timezone.now())

        viernes = (self.today - timedelta(days=3)).isoformat()

        self.assertEqual(
            len(self.rows(date_from=viernes, date_to=viernes, date_basis="issued")),
            1,
        )

    def test_order_still_in_progress_does_not_appear(self):
        """Lo que el técnico aún puede corregir no entra al cuadre.

        Y vuelve solo: en cuanto la orden se cierra, la siguiente consulta del
        mismo periodo ya la trae, sin que nadie tenga que reprocesar nada.
        """
        order = self.make_order(self.make_customer("CLI001"))
        self.add_material(order, self.utp, "30.00")

        self.assertEqual(len(self.rows()), 0)

        self.attend(order, timezone.now())

        self.assertEqual(len(self.rows()), 1)


class FilterTests(LogisticsFeedTestCase):
    """Los recortes que logística pide, y los que se rechazan."""

    def test_branch_filters_by_code(self):
        propia = self.make_order(self.make_customer("CLI001"))
        self.add_material(propia, self.utp)
        self.attend(propia, timezone.now())

        ajena = self.make_order(
            self.make_customer("CLI002", branch=self.other_branch),
            branch=self.other_branch,
        )
        self.add_material(ajena, self.utp)
        self.attend(ajena, timezone.now())

        # Sin sede vienen las dos: un sistema que cuadra todas las sedes no
        # tiene una «sede activa» como la tiene una sesión web.
        self.assertEqual(len(self.rows()), 2)

        filas = self.rows(branch="SED01")
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["branch_code"], "SED01")

    def test_unknown_branch_is_an_error_not_an_empty_list(self):
        """Vacío se leería como «esta sede no movió material esta semana»."""
        respuesta = self.get(branch="NOEXISTE")

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("branch", respuesta.data)

    def test_technician_filter(self):
        otro = User.objects.create_user(
            username="tecnico2",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
        )

        mia = self.make_order(self.make_customer("CLI001"))
        self.add_material(mia, self.utp)
        self.attend(mia, timezone.now())

        suya = self.make_order(self.make_customer("CLI002"))
        WorkOrder.objects.filter(pk=suya.pk).update(assigned_technician=otro)
        self.add_material(suya, self.utp)
        self.attend(suya, timezone.now())

        filas = self.rows(technician=self.technician.pk)

        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["technician_id"], self.technician.pk)

    def test_reversed_period_is_rejected(self):
        respuesta = self.get(
            date_from=self.today.isoformat(),
            date_to=(self.today - timedelta(days=1)).isoformat(),
        )

        self.assertEqual(respuesta.status_code, 400)

    def test_absurd_range_is_rejected(self):
        """Un año mal tecleado pide dos décadas y ocupa al servidor de balde."""
        respuesta = self.get(
            date_from=(self.today - timedelta(days=800)).isoformat(),
            date_to=self.today.isoformat(),
        )

        self.assertEqual(respuesta.status_code, 400)

    def test_missing_dates_are_rejected(self):
        self.assertEqual(self.client.get(LISTA).status_code, 400)


class SyncTests(LogisticsFeedTestCase):
    """Paginación, incremental y reconciliación de borrados."""

    def make_movements(self, cuantos):
        creados = []

        for indice in range(cuantos):
            order = self.make_order(self.make_customer(f"CLI{indice:03d}"))
            creados.append(self.add_material(order, self.utp))
            self.attend(order, timezone.now())

        return creados

    def test_pages_are_walked_with_the_cursor(self):
        """Un mes no viaja en una respuesta: se camina con `next`."""
        self.make_movements(5)

        primera = self.get(page_size=2)
        self.assertEqual(primera.status_code, 200)
        self.assertEqual(len(primera.data["results"]), 2)
        self.assertIsNotNone(primera.data["next"])

        vistos = []
        respuesta = primera

        while True:
            vistos.extend(fila["id"] for fila in respuesta.data["results"])

            if not respuesta.data["next"]:
                break

            respuesta = self.client.get(respuesta.data["next"])

        # Ni se salta ni se repite ninguno.
        self.assertEqual(len(vistos), 5)
        self.assertEqual(len(set(vistos)), 5)

    def test_updated_since_catches_changes_on_the_order_too(self):
        """Liquidar no toca el movimiento, y aun así tiene que volver a salir.

        Es el motivo por el que la marca de agua es el mayor entre los dos
        `updated_at`. Mirando solo el del movimiento, logística recibiría cada
        fila una vez y su `is_liquidated` se quedaría en falso para siempre —
        justo el campo con el que decide si consolida el consumo.
        """
        order = self.make_order(self.make_customer("CLI001"))
        self.add_material(order, self.utp)
        self.attend(order, timezone.now())

        marca = self.get(WATERMARK).data["watermark"]
        self.assertIsNotNone(marca)

        # Nada cambió desde entonces.
        self.assertEqual(len(self.rows(updated_since=marca)), 0)

        # Se liquida la orden: el movimiento no se toca.
        WorkOrderLiquidation.objects.create(
            work_order=order,
            liquidated_by=self.technician,
            liquidated_at=timezone.now(),
            resolution_detail="Conforme.",
            review_status=WorkOrderLiquidation.ReviewStatus.VALIDATED,
        )
        WorkOrder.objects.filter(pk=order.pk).update(updated_at=timezone.now())

        filas = self.rows(updated_since=marca)

        self.assertEqual(len(filas), 1)
        self.assertTrue(filas[0]["is_liquidated"])

    def test_watermark_is_null_when_there_is_nothing(self):
        """`null` se lee como «no muevas tu marca», no como «no hay nada más»."""
        respuesta = self.get(WATERMARK)

        self.assertEqual(respuesta.data["count"], 0)
        self.assertIsNone(respuesta.data["watermark"])

    def test_ids_endpoint_reports_what_still_exists(self):
        """Lo que el otro sistema tiene y aquí ya no aparece, se borra allá.

        Sin esto, un material que el técnico declaró por error y luego quitó
        sobrevive en logística descontando stock que nunca salió del almacén.
        """
        movimientos = self.make_movements(3)

        respuesta = self.get(IDS)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["count"], 3)
        self.assertEqual(
            set(respuesta.data["ids"]),
            {movimiento.pk for movimiento in movimientos},
        )

        borrado = movimientos[0].pk
        movimientos[0].delete()

        self.assertNotIn(borrado, self.get(IDS).data["ids"])

    def test_ids_endpoint_honours_the_same_filters(self):
        """Si recortara distinto que el detalle, borraría filas vigentes."""
        propia = self.make_order(self.make_customer("CLI001"))
        self.add_material(propia, self.utp)
        self.attend(propia, timezone.now())

        ajena = self.make_order(
            self.make_customer("CLI002", branch=self.other_branch),
            branch=self.other_branch,
        )
        self.add_material(ajena, self.utp)
        self.attend(ajena, timezone.now())

        ids = self.get(IDS, branch="SED01").data["ids"]

        self.assertEqual(len(ids), 1)


class ParityTests(LogisticsFeedTestCase):
    """El feed y la hoja tienen que contar lo mismo.

    Es la prueba que protege la decisión de fondo: los dos parten de
    `material_movements()`. El día que alguien le escriba al API su propia
    consulta, la diferencia aparecería en un descuadre de almacén y nadie
    sabría cuál de las dos está mal.
    """

    def test_same_count_as_the_sheet_over_the_same_period(self):
        for indice in range(4):
            order = self.make_order(self.make_customer(f"CLI{indice:03d}"))
            self.add_material(order, self.utp, "10.00")
            self.add_material(
                order,
                self.decoder,
                "1.00",
                WorkOrderMaterialMovement.MovementType.REMOVED,
            )
            self.attend(order, timezone.now())

        hoja = self.report(date_from=self.today, date_to=self.today)
        feed = self.rows(branch="SED01", date_basis="issued")

        self.assertEqual(hoja["total"], len(feed))
        self.assertEqual(hoja["total"], 8)

    def test_quantity_survives_the_trip_with_its_decimals(self):
        """Los metros de fibra se cuadran con dos decimales, no redondeados."""
        order = self.make_order(self.make_customer("CLI001"))
        self.add_material(order, self.utp, "45.50")
        self.attend(order, timezone.now())

        self.assertEqual(Decimal(self.rows()[0]["quantity"]), Decimal("45.50"))
