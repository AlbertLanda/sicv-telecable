"""
Pruebas de la bandeja operativa de despacho de órdenes de trabajo.

Cubren WorkOrderDispatchFilterForm + WorkOrderDispatchListView: acceso,
autorización, listado, búsqueda, filtros combinables, paginación, estado
vacío, visibilidad condicionada de la acción de despacho y ausencia de
consultas N+1.

La bandeja es de solo lectura: no crea órdenes, no cambia estados y no
asigna. Por eso aquí no se verifica ninguna transición -eso ya está probado
en test_assignment.py y test_web_assignment.py-, sino que la bandeja
encuentra lo que debe, no muestra lo que no debe y no abre ningún atajo
hacia el despacho que el permiso ya cerró.
"""

from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.services.models import Subscription
from apps.work_orders.models import OrderType, WorkOrder
from apps.work_orders.tests.base import User, WorkOrderTestCase


class WorkOrderDispatchTestCase(WorkOrderTestCase):
    """
    Escenario común: un despachador con permiso de visualización.

    El despachador se define por PERMISO, no por rol: se parte de un
    supervisor sin permisos y se le concede view_workorder explícitamente,
    para dejar claro que lo que abre la bandeja es el permiso y nada más.
    """

    def setUp(self):
        super().setUp()

        self.url = reverse("work_orders:dispatch")

        self.view_permission = Permission.objects.get(
            codename="view_workorder",
            content_type__app_label="work_orders",
        )

        self.assign_permission = Permission.objects.get(
            codename="assign_workorder",
            content_type__app_label="work_orders",
        )

        self.dispatcher = self.supervisor
        self.dispatcher.user_permissions.add(self.view_permission)

        self.client.login(username="supervisor1", password="test1234")

    # -- Utilidades -------------------------------------------------------

    def grant_assign_permission(self):
        """Habilita el despacho al usuario que ya puede ver la bandeja."""
        self.dispatcher.user_permissions.add(self.assign_permission)

        # Django cachea los permisos en la instancia tras la primera consulta.
        # Sin re-login, el request seguiría viendo los permisos anteriores.
        self.client.login(username="supervisor1", password="test1234")

    def assign_url(self, order):
        return reverse("work_orders:assign", kwargs={"pk": order.pk})

    def orders_in_response(self, response):
        """Números de orden que la bandeja está mostrando."""
        return [
            order.order_number
            for order in response.context["orders"]
        ]

    def create_second_customer(self):
        """Segundo cliente con suscripción propia, para acotar búsquedas."""
        customer = Customer.objects.create(
            code="CLI002",
            branch=self.branch,
            document_type=Customer.DocumentType.RUC,
            document_number="20487654321",
            business_name="Comercial Amazonas SAC",
        )

        address = CustomerAddress.objects.create(
            customer=customer,
            zone=self.zone,
            address="Jr. Ortiz Arrieta 100",
            district="Chachapoyas",
            is_primary=True,
        )

        subscription = Subscription.objects.create(
            customer=customer,
            address=address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
        )

        return customer, subscription


class DispatchAccessTests(WorkOrderDispatchTestCase):
    """Escenarios 1, 2 y 3: quién puede abrir la bandeja y quién no."""

    def test_authorized_user_opens_the_board(self):
        """1. Un usuario con permiso obtiene 200 y ve el listado."""
        order = self.create_order()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "work_orders/work_order_dispatch.html",
        )
        self.assertIn(order.order_number, self.orders_in_response(response))

    def test_anonymous_user_is_redirected_to_login(self):
        """2. Sin sesión no hay bandeja: se redirige al login."""
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_user_without_view_permission_gets_403(self):
        """3. Autenticado pero sin view_workorder: 403, no un listado vacío."""
        self.client.login(username="atc1", password="test1234")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_board_does_not_open_a_shortcut_to_assignment(self):
        """
        3 (continuación). Ver la bandeja no habilita despachar.

        El despachador de estas pruebas tiene view_workorder pero no
        assign_workorder: escribir la URL de asignación a mano sigue dando
        403, tanto en GET como en POST. La bandeja no relaja el permiso
        funcional que protege la asignación.
        """
        order = self.create_order()

        self.assertEqual(
            self.client.get(self.assign_url(order)).status_code,
            403,
        )

        response = self.client.post(
            self.assign_url(order),
            {"assigned_technician": self.technician.pk},
        )

        self.assertEqual(response.status_code, 403)

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(order.assigned_technician)


class DispatchListingTests(WorkOrderDispatchTestCase):
    """Escenario 4: el listado muestra lo esperado y sin duplicados."""

    def test_board_lists_every_order_once(self):
        """4. Varias OT se listan completas y sin filas repetidas."""
        orders = [self.create_order() for _ in range(3)]

        response = self.client.get(self.url)

        listed = self.orders_in_response(response)

        self.assertEqual(len(listed), len(set(listed)))

        for order in orders:
            self.assertIn(order.order_number, listed)

    def test_board_orders_newest_first(self):
        """El ordenamiento es estable y por creación descendente."""
        first = self.create_order()
        second = self.create_order()
        third = self.create_order()

        response = self.client.get(self.url)

        self.assertEqual(
            self.orders_in_response(response),
            [
                third.order_number,
                second.order_number,
                first.order_number,
            ],
        )

    def test_board_shows_the_assigned_technician_and_the_unassigned_mark(self):
        """Una OT con técnico lo muestra; una sin técnico dice Sin asignar."""
        self.create_order()
        assigned = self.create_assigned_order()

        response = self.client.get(self.url)

        self.assertContains(response, str(assigned.assigned_technician))
        self.assertContains(response, "Sin asignar")


class DispatchSearchTests(WorkOrderDispatchTestCase):
    """Escenarios 5 y 6: búsqueda por orden y por identidad del cliente."""

    def setUp(self):
        super().setUp()

        self.own_order = self.create_order()

        self.other_customer, self.other_subscription = (
            self.create_second_customer()
        )

        self.other_order = self.create_order(
            subscription=self.other_subscription,
        )

    def test_search_by_order_number_returns_the_exact_order(self):
        """5. Buscar el número de OT devuelve esa orden y solo esa."""
        response = self.client.get(
            self.url,
            {"q": self.own_order.order_number},
        )

        self.assertEqual(
            self.orders_in_response(response),
            [self.own_order.order_number],
        )

    def test_search_by_customer_code_returns_that_customers_orders(self):
        """6. Buscar el código de cliente acota a sus órdenes."""
        response = self.client.get(self.url, {"q": self.other_customer.code})

        self.assertEqual(
            self.orders_in_response(response),
            [self.other_order.order_number],
        )

    def test_search_by_document_number_returns_that_customers_orders(self):
        """6. Buscar el documento de identidad acota a sus órdenes."""
        response = self.client.get(
            self.url,
            {"q": self.customer.document_number},
        )

        self.assertEqual(
            self.orders_in_response(response),
            [self.own_order.order_number],
        )

    def test_search_by_business_name_returns_that_customers_orders(self):
        """6. La razón social también es un criterio de búsqueda."""
        response = self.client.get(self.url, {"q": "Comercial Amazonas"})

        self.assertEqual(
            self.orders_in_response(response),
            [self.other_order.order_number],
        )

    def test_search_by_customer_name_matches_every_word(self):
        """Las palabras se exigen en conjunto, no por separado."""
        response = self.client.get(self.url, {"q": "Juan Pérez"})

        self.assertEqual(
            self.orders_in_response(response),
            [self.own_order.order_number],
        )

    def test_search_ignores_surrounding_whitespace(self):
        """Un término con espacios sobrantes no rompe la búsqueda."""
        response = self.client.get(
            self.url,
            {"q": f"   {self.own_order.order_number}   "},
        )

        self.assertEqual(
            self.orders_in_response(response),
            [self.own_order.order_number],
        )


class DispatchFilterTests(WorkOrderDispatchTestCase):
    """Escenarios 7 a 12: filtros individuales, combinados y sin resultados."""

    def setUp(self):
        super().setUp()

        self.other_branch = Branch.objects.create(
            code="SED02",
            name="Sede Bagua",
        )

        self.other_zone = Zone.objects.create(
            branch=self.other_branch,
            name="Zona Sur",
        )

        self.repair_type = OrderType.objects.create(
            code="AVERIA_BANDEJA",
            name="Avería",
        )

        # OT pendiente, sede central, zona norte, instalación, prioridad normal.
        self.pending_order = self.create_order()

        # OT ya asignada, otra sede, otra zona, avería y prioridad urgente.
        self.assigned_order = self.create_assigned_order(
            order_type=self.repair_type,
            branch=self.other_branch,
            zone=self.other_zone,
            priority=WorkOrder.Priority.URGENT,
        )

    def test_filter_by_status(self):
        """7. Filtrar por PENDING deja solo las órdenes pendientes."""
        response = self.client.get(
            self.url,
            {"status": WorkOrder.Status.PENDING},
        )

        self.assertEqual(
            self.orders_in_response(response),
            [self.pending_order.order_number],
        )

    def test_filter_by_branch(self):
        """8. Filtrar por sede deja solo las órdenes de esa sede."""
        response = self.client.get(self.url, {"branch": self.branch.pk})

        self.assertEqual(
            self.orders_in_response(response),
            [self.pending_order.order_number],
        )

    def test_branch_filter_does_not_restrict_eligible_technicians(self):
        """
        8 (regla crítica). Filtrar por sede organiza el listado; no decide
        qué técnico puede atender.

        Con el filtro de sede aplicado, un técnico activo de OTRA sede sigue
        siendo elegible en el flujo de asignación de una orden listada.
        """
        foreign_technician = User.objects.create_user(
            username="tecnico_ajeno",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=self.other_branch,
        )

        self.grant_assign_permission()

        board = self.client.get(self.url, {"branch": self.branch.pk})

        self.assertEqual(
            self.orders_in_response(board),
            [self.pending_order.order_number],
        )

        assignment = self.client.get(self.assign_url(self.pending_order))

        eligible = (
            assignment.context["form"]
            .fields["assigned_technician"]
            .queryset
        )

        self.assertIn(foreign_technician, eligible)

    def test_filter_by_zone(self):
        """9. Filtrar por zona deja solo las órdenes de esa zona."""
        response = self.client.get(self.url, {"zone": self.other_zone.pk})

        self.assertEqual(
            self.orders_in_response(response),
            [self.assigned_order.order_number],
        )

    def test_filter_by_order_type(self):
        """10. Filtrar por tipo de orden deja solo ese tipo."""
        response = self.client.get(
            self.url,
            {"order_type": self.repair_type.pk},
        )

        self.assertEqual(
            self.orders_in_response(response),
            [self.assigned_order.order_number],
        )

    def test_filter_by_priority(self):
        """11. Filtrar por prioridad deja solo las órdenes esperadas."""
        response = self.client.get(
            self.url,
            {"priority": WorkOrder.Priority.URGENT},
        )

        self.assertEqual(
            self.orders_in_response(response),
            [self.assigned_order.order_number],
        )

    def test_filter_by_assigned_technician(self):
        """Filtrar por técnico deja solo lo despachado a esa persona."""
        response = self.client.get(
            self.url,
            {"technician": str(self.technician.pk)},
        )

        self.assertEqual(
            self.orders_in_response(response),
            [self.assigned_order.order_number],
        )

    def test_filter_by_unassigned(self):
        """El valor "sin asignar" deja solo las órdenes sin técnico."""
        response = self.client.get(self.url, {"technician": "unassigned"})

        self.assertEqual(
            self.orders_in_response(response),
            [self.pending_order.order_number],
        )

    def test_filters_combine(self):
        """Los filtros se acumulan en vez de sustituirse."""
        response = self.client.get(
            self.url,
            {
                "status": WorkOrder.Status.PENDING,
                "branch": self.branch.pk,
                "zone": self.zone.pk,
            },
        )

        self.assertEqual(
            self.orders_in_response(response),
            [self.pending_order.order_number],
        )

    def test_incompatible_filters_show_a_clear_empty_state(self):
        """12. Sin coincidencias: estado vacío explicado, no un error."""
        response = self.client.get(
            self.url,
            {
                "status": WorkOrder.Status.PENDING,
                "branch": self.other_branch.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.orders_in_response(response), [])
        self.assertContains(response, "No hay órdenes que coincidan")

    def test_board_without_orders_explains_it_is_empty(self):
        """Sin filtros y sin órdenes el mensaje es otro: todavía no hay OT."""
        WorkOrder.objects.all().delete()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Todavía no hay órdenes")

    def test_unknown_filter_values_do_not_break_the_board(self):
        """
        Un parámetro corrupto anula su propio filtro, no la consulta entera.

        El formulario descarta ?branch=999999 y ?status=BASURA sin llegar al
        queryset -no hay SQL construido con la entrada del operador-, y el
        filtro válido que lo acompaña se sigue aplicando.
        """
        response = self.client.get(
            self.url,
            {
                "branch": "999999",
                "status": WorkOrder.Status.PENDING,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.orders_in_response(response),
            [self.pending_order.order_number],
        )


class DispatchPaginationTests(WorkOrderDispatchTestCase):
    """Escenario 13: paginación y filtros que sobreviven a la navegación."""

    def test_board_paginates_long_listings(self):
        """13. Al superar el tamaño de página se navega entre páginas."""
        page_size = 20

        for _ in range(page_size + 3):
            self.create_order()

        first_page = self.client.get(self.url)

        self.assertTrue(first_page.context["is_paginated"])
        self.assertEqual(len(first_page.context["orders"]), page_size)
        self.assertEqual(first_page.context["paginator"].num_pages, 2)

        second_page = self.client.get(self.url, {"page": 2})

        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.context["orders"]), 3)

        # Ninguna orden aparece en las dos páginas: el orden es estable.
        self.assertFalse(
            set(self.orders_in_response(first_page))
            & set(self.orders_in_response(second_page))
        )

    def test_filters_survive_pagination(self):
        """Los filtros viajan en los enlaces de página y siguen aplicándose."""
        for _ in range(21):
            self.create_order(priority=WorkOrder.Priority.URGENT)

        self.create_order(priority=WorkOrder.Priority.LOW)

        first_page = self.client.get(
            self.url,
            {"priority": WorkOrder.Priority.URGENT},
        )

        self.assertEqual(
            first_page.context["querystring"],
            "priority=URGENT",
        )
        self.assertContains(first_page, "priority=URGENT&amp;page=2")

        second_page = self.client.get(
            self.url,
            {"priority": WorkOrder.Priority.URGENT, "page": 2},
        )

        self.assertEqual(len(second_page.context["orders"]), 1)

        for order in second_page.context["orders"]:
            self.assertEqual(order.priority, WorkOrder.Priority.URGENT)


class DispatchActionVisibilityTests(WorkOrderDispatchTestCase):
    """Escenarios 14 a 17: cuándo se ofrece Asignar y cuándo Reasignar."""

    def test_assign_action_is_offered_for_assignable_orders(self):
        """14. Con permiso y OT asignable, la bandeja ofrece Asignar."""
        order = self.create_order()

        self.grant_assign_permission()

        response = self.client.get(self.url)

        self.assertContains(response, self.assign_url(order))
        self.assertContains(response, "Asignar")

    def test_assign_action_is_hidden_without_permission(self):
        """15. Sin assign_workorder la acción no se muestra."""
        order = self.create_order()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.assign_url(order))

    def test_closed_orders_do_not_offer_assignment(self):
        """16. Una OT cerrada no ofrece Asignar ni Reasignar."""
        self.grant_assign_permission()

        for status in (
            WorkOrder.Status.CANCELLED,
            WorkOrder.Status.ATTENDED,
            WorkOrder.Status.LIQUIDATED,
        ):
            with self.subTest(status=status):
                order = self.create_order(status=status)

                response = self.client.get(
                    self.url,
                    {"q": order.order_number},
                )

                self.assertEqual(
                    self.orders_in_response(response),
                    [order.order_number],
                )
                self.assertNotContains(response, self.assign_url(order))

    def test_assigned_orders_offer_reassignment(self):
        """17. Una OT asignada ofrece Reasignar hacia el flujo existente."""
        order = self.create_assigned_order()

        self.grant_assign_permission()

        response = self.client.get(self.url, {"q": order.order_number})

        self.assertContains(response, self.assign_url(order))
        self.assertContains(response, "Reasignar")


class DispatchQueryTests(WorkOrderDispatchTestCase):
    """Escenario 18: el listado no crece en consultas por cada fila."""

    def test_listing_does_not_issue_queries_per_order(self):
        """
        18. Listar N órdenes cuesta lo mismo que listar una.

        Se compara el número de consultas con una orden y con varias en vez
        de fijar una cifra exacta: lo que se quiere probar es la ausencia de
        N+1, no congelar cuántas consultas hace Django para autenticar.
        """
        self.grant_assign_permission()

        self.create_order()

        with CaptureQueriesContext(connection) as single:
            self.client.get(self.url)

        for _ in range(5):
            self.create_assigned_order()

        with CaptureQueriesContext(connection) as several:
            self.client.get(self.url)

        self.assertEqual(
            len(several.captured_queries),
            len(single.captured_queries),
            "El listado dispara consultas adicionales por cada orden: "
            "revisar select_related.",
        )


class DispatchUrlTests(TestCase):
    """La bandeja vive en su propia ruta del módulo de órdenes."""

    def test_dispatch_url_resolves(self):
        self.assertEqual(
            reverse("work_orders:dispatch"),
            "/work-orders/dispatch/",
        )
