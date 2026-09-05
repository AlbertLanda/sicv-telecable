"""
Pruebas del tablero de programación semanal y de su endpoint de reprogramación.

El tablero agrupa por **fecha**, no por estado, así que lo que se fija aquí no
es un listado más: es que la columna de una orden sea su día de atención, que
la semana navegue de lunes a domingo, y que mover una tarjeta delegue en
`WorkOrder.reprogram()` en lugar de escribir `scheduled_at` por su cuenta.

Las tres reglas del dominio que el tablero no puede saltarse —solo ciertos
estados admiten reprogramación, la fecha debe ser futura, y reprogramar deja la
orden bloqueada hasta que se reasigne— se prueban desde el endpoint, no desde
el modelo: el modelo ya las tiene cubiertas en `test_workflow`, y lo que falta
comprobar es que la vista las respete en vez de reimplementarlas.

Las fechas se calculan **relativas al lunes de la semana en curso**, nunca con
desplazamientos fijos desde hoy: un `+3 días` cae fuera de la semana visible si
la prueba corre en viernes, y la suite pasaría o fallaría según el día en que
se ejecute.
"""

import json
from datetime import datetime, time, timedelta

from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.work_orders.models import WorkOrder
from apps.work_orders.tests.base import WorkOrderTestCase


class ScheduleBoardTestCase(WorkOrderTestCase):
    """Base común: un usuario que consulta y otro que además despacha."""

    def setUp(self):
        super().setUp()

        self.url = reverse("work_orders:schedule_board")

        self.today = timezone.localdate()
        self.week_start = self.today - timedelta(days=self.today.weekday())
        self.week_end = self.week_start + timedelta(days=6)

        view_permission = Permission.objects.get(
            codename="view_workorder",
            content_type__app_label="work_orders",
        )
        assign_permission = Permission.objects.get(
            codename="assign_workorder",
            content_type__app_label="work_orders",
        )

        self.viewer = self.make_user("consulta1")
        self.viewer.user_permissions.add(view_permission)

        self.dispatcher = self.make_user("despacho1")
        self.dispatcher.user_permissions.add(view_permission, assign_permission)

    def make_user(self, username):
        from apps.accounts.models import User

        return User.objects.create_user(
            username=username,
            password="test1234",
            role=User.Role.ATC,
            branch=self.branch,
        )

    def login(self, user):
        self.client.login(username=user.username, password="test1234")

        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = self.branch.pk
        session.save()

    def at(self, day, hour=10, minute=0):
        """Un `datetime` con zona en el día indicado."""
        return timezone.make_aware(
            datetime.combine(day, time(hour, minute)),
            timezone.get_current_timezone(),
        )

    def board(self, **params):
        return self.client.get(self.url, params)

    def every_order(self, response):
        columns = (
            [response.context["unscheduled_column"]]
            + list(response.context["day_columns"])
        )

        return [order for column in columns for order in column["orders"]]

    def reschedule_url(self, order):
        return reverse("work_orders:reschedule", args=[order.pk])

    def reschedule(self, order, day):
        return self.client.post(
            self.reschedule_url(order),
            data=json.dumps({"date": day.isoformat()}),
            content_type="application/json",
        )


class ScheduleBoardAccessTests(ScheduleBoardTestCase):
    """Quién entra al tablero."""

    def test_anonymous_is_redirected_to_login(self):
        response = self.board()

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_without_view_permission_it_is_forbidden(self):
        """403 y no un tablero vacío.

        Un tablero vacío diría «no hay órdenes», que es falso y distinto de
        «no puede verlas».
        """
        self.login(self.make_user("sinpermiso"))

        self.assertEqual(self.board().status_code, 403)

    def test_with_view_permission_it_renders(self):
        self.login(self.viewer)

        response = self.board()

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "work_orders/work_order_schedule_board.html",
        )


class ScheduleBoardWeekTests(ScheduleBoardTestCase):
    """La semana que se muestra y cómo se navega."""

    def test_the_week_runs_monday_to_sunday(self):
        self.login(self.viewer)

        response = self.board()
        days = response.context["day_columns"]

        self.assertEqual(len(days), 7)
        self.assertEqual(days[0]["date"], self.week_start)
        self.assertEqual(days[-1]["date"], self.week_end)
        self.assertEqual(days[0]["date"].weekday(), 0)
        self.assertEqual(days[-1]["date"].weekday(), 6)

    def test_by_default_it_opens_on_the_current_week(self):
        self.login(self.viewer)

        response = self.board()

        self.assertTrue(response.context["is_current_week"])
        self.assertEqual(response.context["week_start"], self.week_start)

    def test_any_day_of_a_week_opens_that_week(self):
        """El parámetro admite cualquier día, no solo el lunes.

        Un enlace copiado a media semana tiene que llevar a esa semana, no
        fallar ni saltar a otra.
        """
        self.login(self.viewer)

        thursday = self.week_start + timedelta(days=3, weeks=2)

        response = self.board(fecha=thursday.isoformat())

        self.assertEqual(
            response.context["week_start"],
            self.week_start + timedelta(weeks=2),
        )
        self.assertFalse(response.context["is_current_week"])

    def test_an_invalid_date_falls_back_to_the_current_week(self):
        """Una fecha rota no revienta el tablero.

        El parámetro viaja en la URL y cualquiera puede escribir en ella; caer
        a la semana en curso es más útil que un 500 o un 400.
        """
        self.login(self.viewer)

        response = self.board(fecha="no-es-una-fecha")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_current_week"])

    def test_orders_of_another_week_are_not_shown(self):
        order = self.create_assigned_order(
            scheduled_at=self.at(self.week_start + timedelta(weeks=3)),
        )

        self.login(self.viewer)

        self.assertNotIn(order, self.every_order(self.board()))

    def test_navigating_to_that_week_shows_them(self):
        target = self.week_start + timedelta(weeks=3)
        order = self.create_assigned_order(scheduled_at=self.at(target))

        self.login(self.viewer)

        response = self.board(fecha=target.isoformat())

        self.assertIn(order, self.every_order(response))


class ScheduleBoardColumnTests(ScheduleBoardTestCase):
    """Dónde cae cada orden."""

    def test_an_order_lands_in_the_column_of_its_scheduled_day(self):
        order = self.create_assigned_order(scheduled_at=self.at(self.today))

        self.login(self.viewer)

        days = self.board().context["day_columns"]
        column = next(c for c in days if c["date"] == self.today)

        self.assertIn(order, column["orders"])

    def test_orders_without_a_date_go_to_the_tray(self):
        order = self.create_assigned_order(scheduled_at=None)

        self.login(self.viewer)

        tray = self.board().context["unscheduled_column"]

        self.assertEqual(tray["key"], "unscheduled")
        self.assertIn(order, tray["orders"])

    def test_the_tray_does_not_accept_drops(self):
        """No se puede devolver una tarjeta a «Sin programar».

        `reprogram()` exige una fecha: dejarla en blanco no es una
        reprogramación que el dominio sepa expresar.
        """
        self.login(self.viewer)

        self.assertFalse(self.board().context["unscheduled_column"]["is_droppable"])

    def test_past_days_are_locked_and_today_is_checked_by_its_time(self):
        """Hoy puede recibir la OT si la hora todavía es futura."""
        self.login(self.viewer)

        for column in self.board().context["day_columns"]:
            with self.subTest(dia=column["date"]):
                if column["date"] < self.today:
                    self.assertFalse(column["is_droppable"])
                else:
                    self.assertTrue(column["is_droppable"])

    def test_weekend_columns_are_marked(self):
        self.login(self.viewer)

        days = self.board().context["day_columns"]

        self.assertEqual(
            [column["is_weekend"] for column in days],
            [False, False, False, False, False, True, True],
        )

    def test_closed_orders_are_not_shown(self):
        """Una orden cerrada ya no se planifica.

        Llenar el tablero con trabajo terminado escondería el que falta.
        """
        order = self.create_attended_order()

        self.login(self.viewer)

        self.assertNotIn(order, self.every_order(self.board()))

    def test_orders_of_another_branch_are_not_shown(self):
        """El tablero es el de la sede activa, no el de todo el sistema."""
        from apps.organization.models import Branch

        other = Branch.objects.create(code="OTRA", name="Otra sede")

        order = self.create_assigned_order(scheduled_at=self.at(self.today))
        order.branch = other
        order.save(update_fields=["branch"])

        self.login(self.viewer)

        self.assertNotIn(order, self.every_order(self.board()))


class ScheduleBoardStatsTests(ScheduleBoardTestCase):
    """Los indicadores de la cabecera."""

    def test_stats_count_the_whole_branch_not_only_the_visible_week(self):
        """Son el motivo por el que uno navega a otra semana.

        Si «Sin programar» contara solo la semana en pantalla marcaría cero
        mientras queda trabajo sin colocar, que es justo el dato que hay que
        ver. Se comprueba desde una semana lejana, donde el sesgo se notaría.
        """
        self.create_assigned_order(scheduled_at=None)
        self.create_assigned_order(scheduled_at=None)

        self.login(self.viewer)

        far = (self.week_start + timedelta(weeks=6)).isoformat()
        stats = self.board(fecha=far).context["stats"]

        self.assertEqual(stats["unscheduled"], 2)
        self.assertEqual(stats["week"], 0)

    def test_the_week_counter_only_counts_the_visible_week(self):
        """Ese sí es de la semana: dice cuánto trabajo hay en pantalla."""
        self.create_assigned_order(scheduled_at=self.at(self.today))
        self.create_assigned_order(
            scheduled_at=self.at(self.week_start + timedelta(weeks=2)),
        )

        self.login(self.viewer)

        self.assertEqual(self.board().context["stats"]["week"], 1)

    def test_overdue_counts_orders_whose_day_already_passed(self):
        self.create_assigned_order(
            scheduled_at=self.at(self.today - timedelta(days=3)),
        )

        self.login(self.viewer)

        self.assertEqual(self.board().context["stats"]["overdue"], 1)

    def test_unassigned_counts_orders_without_a_technician(self):
        self.create_order()

        self.login(self.viewer)

        self.assertEqual(self.board().context["stats"]["unassigned"], 1)

    def test_closed_orders_do_not_reach_the_stats(self):
        """El mismo criterio que el tablero: lo cerrado ya no se planifica."""
        self.create_attended_order()

        self.login(self.viewer)

        stats = self.board().context["stats"]

        self.assertEqual(stats["unassigned"], 0)
        self.assertEqual(stats["week"], 0)


class RescheduleEndpointTests(ScheduleBoardTestCase):
    """Mover una tarjeta."""

    def future(self, days=3):
        return self.today + timedelta(days=days)

    def test_moving_a_card_delegates_to_the_domain(self):
        """La vista no escribe `scheduled_at`: llama a `reprogram()`.

        Se comprueba por sus efectos completos —fecha nueva, estado
        REPROGRAMMED e histórico registrado—, porque escribir el campo a mano
        produciría el primero sin los otros dos.
        """
        order = self.create_assigned_order(
            scheduled_at=self.at(self.today + timedelta(days=1)),
        )
        target = self.future(4)

        self.login(self.dispatcher)

        response = self.reschedule(order, target)
        order.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(timezone.localtime(order.scheduled_at).date(), target)
        self.assertEqual(order.status, WorkOrder.Status.REPROGRAMMED)
        self.assertEqual(order.reprogrammings.count(), 1)

    def test_the_time_of_day_is_preserved(self):
        """Arrastrar cambia el día, no la hora.

        Si el técnico iba a las 15:30, sigue yendo a las 15:30 otro día: esa
        hora la acordó alguien con el cliente y el tablero no la conoce.
        """
        order = self.create_assigned_order(
            scheduled_at=self.at(self.today + timedelta(days=1), hour=15, minute=30),
        )

        self.login(self.dispatcher)
        self.reschedule(order, self.future(6))

        order.refresh_from_db()
        moved = timezone.localtime(order.scheduled_at)

        self.assertEqual((moved.hour, moved.minute), (15, 30))

    def test_an_unscheduled_order_gets_a_default_time(self):
        """Sin hora previa no hay nada que conservar: se usa la de apertura."""
        order = self.create_assigned_order(scheduled_at=None)

        self.login(self.dispatcher)
        self.reschedule(order, self.future(2))

        order.refresh_from_db()
        moved = timezone.localtime(order.scheduled_at)

        self.assertEqual((moved.hour, moved.minute), (9, 0))

    def test_a_past_date_is_rejected_with_the_domain_message(self):
        """El mensaje es el del dominio, no uno genérico.

        El operador tiene que leer la razón real para saber qué hacer distinto.
        """
        order = self.create_assigned_order(
            scheduled_at=self.at(self.today + timedelta(days=1)),
        )

        self.login(self.dispatcher)

        response = self.reschedule(order, self.today - timedelta(days=1))
        order.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertIn("futura", response.json()["message"])
        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)

    def test_pending_order_can_be_programmed_before_assignment(self):
        """Programar una OT PENDING no obliga a asignar un técnico."""
        order = self.create_order()

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(order.assigned_technician_id)

        self.login(self.dispatcher)

        response = self.reschedule(order, self.future())
        order.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(order.assigned_technician_id)
        self.assertEqual(order.reprogrammings.count(), 1)

    def test_a_second_move_is_rejected_until_it_is_reassigned(self):
        """La restricción que el tablero anuncia por adelantado.

        Reprogramar deja la orden en REPROGRAMMED, y ese estado no admite otra
        reprogramación. Se fija aquí para que nadie la relaje sin decidirlo:
        cambiarla es una decisión de negocio, y esta prueba es donde se
        notaría.
        """
        order = self.create_assigned_order(
            scheduled_at=self.at(self.today + timedelta(days=1)),
        )

        self.login(self.dispatcher)

        self.reschedule(order, self.future(3))
        second = self.reschedule(order, self.future(5))

        self.assertEqual(second.status_code, 400)
        self.assertIn("Reprogramada", second.json()["message"])

        order.refresh_from_db()
        self.assertEqual(order.reprogrammings.count(), 1)

    def test_viewing_the_board_does_not_grant_moving_cards(self):
        """Ver y despachar son permisos distintos.

        Quien consulta la programación puede verla entera; decidir cuándo
        trabaja un técnico es otra cosa.
        """
        order = self.create_assigned_order(
            scheduled_at=self.at(self.today + timedelta(days=1)),
        )

        self.login(self.viewer)

        response = self.reschedule(order, self.future())
        order.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)

    def test_a_malformed_request_does_not_crash(self):
        order = self.create_assigned_order()

        self.login(self.dispatcher)

        response = self.client.post(
            self.reschedule_url(order),
            data="no es json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_a_missing_date_is_reported(self):
        order = self.create_assigned_order()

        self.login(self.dispatcher)

        response = self.client.post(
            self.reschedule_url(order),
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("fecha", response.json()["message"].lower())
