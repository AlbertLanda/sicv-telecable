"""
Cómo se llega a la cuenta de un abonado.

Deuda, historial y comprobantes no son módulos aparte: son el mismo cliente
visto desde otro ángulo, así que se navegan como pestañas de su ficha. Antes
colgaban del menú lateral y resolvían «de quién» leyendo la sesión, que es un
estado que el operador no ve: el mismo clic abría una cuenta o rebotaba al
buscador según lo que se hubiera hecho antes.
"""

from django.urls import reverse

from apps.customers.models import Customer
from apps.payments.tests.base import PaymentsTestCase


class TheFichaOffersTheAccountTests(PaymentsTestCase):
    """La ficha del cliente es el punto de entrada a su cuenta."""

    def setUp(self):
        super().setUp()

        self.user = self.make_user(
            "atc1", permissions=["view_charge", "view_payment", "view_receipt"]
        )

    def ficha(self):
        return self.client.get(
            reverse("customers:detail", args=[self.customer.pk])
        )

    def test_the_ficha_links_to_the_three_account_screens(self):
        self.login(self.user)

        response = self.ficha()

        self.assertContains(
            response, reverse("payments:debt", args=[self.customer.pk])
        )
        self.assertContains(
            response, reverse("payments:history", args=[self.customer.pk])
        )
        self.assertContains(
            response, reverse("payments:receipts", args=[self.customer.pk])
        )

    def test_each_tab_answers_to_its_own_permission(self):
        """Ver la deuda, los pagos y los comprobantes son tres permisos."""
        self.login(self.make_user("solodeuda", permissions=["view_charge"]))

        response = self.ficha()

        self.assertContains(
            response, reverse("payments:debt", args=[self.customer.pk])
        )
        self.assertNotContains(
            response, reverse("payments:history", args=[self.customer.pk])
        )
        self.assertNotContains(
            response, reverse("payments:receipts", args=[self.customer.pk])
        )

    def test_without_any_payments_permission_the_ficha_offers_no_account(self):
        self.login(self.make_user("sinpagos", permissions=[]))

        response = self.ficha()

        self.assertNotContains(
            response, reverse("payments:debt", args=[self.customer.pk])
        )

    def test_the_information_tab_leaves_the_debt_to_its_own_tab(self):
        """Información responde qué tiene contratado, no cuánto debe.

        Las cifras de deuda encabezaban también esta pestaña, y entre eso, la
        OT destacada y las vistas previas, había que bajar seis bloques para
        llegar al primer dato del cliente.
        """
        self.login(self.user)

        response = self.ficha()

        self.assertNotContains(response, "Deudas abiertas")
        self.assertNotContains(response, "Vencimiento más antiguo")

    def test_the_debt_tab_is_the_one_that_carries_the_figures(self):
        self.login(self.user)

        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertContains(response, "Deudas abiertas")
        self.assertContains(response, "Vencimiento más antiguo")

    def test_the_ficha_links_to_the_orders_and_activity_tabs(self):
        """Órdenes y actividad también salieron de la ficha a su pestaña."""
        self.login(self.user)

        response = self.ficha()

        self.assertContains(
            response, reverse("customers:orders", args=[self.customer.pk])
        )
        self.assertContains(
            response, reverse("customers:activity", args=[self.customer.pk])
        )

    def test_collecting_lives_in_the_overflow_menu_not_in_the_bar(self):
        """Cobrar se hace desde la deuda, marcando los cargos que se saldan.

        En la barra invitaba a abrir el cobro sin haber elegido nada. Queda en
        el menú por el caso que la pestaña Deuda no cubre: el abonado que
        adelanta dinero sin deber nada, al que el botón «Cobrar» de esa
        pantalla ni siquiera se le muestra porque no tiene cargos.
        """
        self.login(
            self.make_user(
                "ventanilla", permissions=["view_charge", "add_payment"]
            )
        )
        url = reverse("payments:register", args=[self.customer.pk])

        response = self.ficha()

        # Una sola vez: si siguiera tambien en la barra, saldria dos.
        self.assertContains(response, url, count=1)
        self.assertInHTML(
            '<a class="dropdown-item" href="%s">'
            '<i class="bi bi-cash-coin"></i>Registrar cobro</a>' % url,
            response.content.decode(),
            count=1,
        )

    def test_the_ficha_hides_the_collect_action_from_who_may_not(self):
        self.login(self.user)

        response = self.ficha()

        self.assertNotContains(
            response, reverse("payments:register", args=[self.customer.pk])
        )


class TheAccountScreensStayOnTheCustomerTests(PaymentsTestCase):
    """Desde cualquier pestaña se alcanza el resto sin volver al buscador."""

    SCREENS = (
        "customers:detail",
        "customers:orders",
        "payments:debt",
        "payments:history",
        "payments:receipts",
        "customers:activity",
    )

    def setUp(self):
        super().setUp()

        self.user = self.make_user(
            "atc1", permissions=["view_charge", "view_payment", "view_receipt"]
        )
        self.login(self.user)

    def test_every_account_screen_carries_the_whole_strip(self):
        for screen in self.SCREENS:
            with self.subTest(screen=screen):
                response = self.client.get(
                    reverse(screen, args=[self.customer.pk])
                )

                self.assertContains(
                    response,
                    reverse("customers:detail", args=[self.customer.pk]),
                )

                for other in self.SCREENS:
                    self.assertContains(
                        response, reverse(other, args=[self.customer.pk])
                    )

    def test_the_open_screen_is_the_one_marked_as_current(self):
        url = reverse("payments:history", args=[self.customer.pk])

        response = self.client.get(url)

        self.assertInHTML(
            '<a href="%s" class="active" aria-current="page">'
            '<i class="bi bi-clock-history"></i>Historial de pagos</a>' % url,
            response.content.decode(),
            count=1,
        )

    def test_the_account_screens_do_not_depend_on_the_session(self):
        """Sin nada elegido en la sesión, la URL del abonado basta.

        Es lo que se ganó al sacarlas del menú: la pantalla ya no tiene que
        adivinar de quién se habla.
        """
        session = self.client.session
        session.pop("selected_customer_id", None)
        session.save()

        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["customer"], self.customer)

    def test_another_customer_account_is_one_url_away(self):
        other = Customer.objects.create(
            code="CLI002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="10101010",
            first_name="Ana",
            paternal_surname="Lopez",
        )

        response = self.client.get(reverse("payments:debt", args=[other.pk]))

        self.assertEqual(response.context["customer"], other)


class TheMenuDoesNotHoldSingleCustomerScreensTests(PaymentsTestCase):
    """El menú lateral navega procesos, no registros concretos."""

    def test_the_menu_offers_no_account_of_any_customer(self):
        self.login(
            self.make_user(
                "atc1",
                permissions=["view_charge", "view_payment", "view_receipt"],
            )
        )

        response = self.client.get(reverse("customers:search"))

        self.assertNotContains(
            response, reverse("payments:debt", args=[self.customer.pk])
        )

    def test_the_menu_keeps_a_place_for_the_lists_that_cross_customers(self):
        """Cartera, caja y compromisos sí son del menú. Aún no existen."""
        self.login(self.make_user("atc1", permissions=["view_charge"]))

        response = self.client.get(reverse("customers:search"))

        self.assertContains(response, "Cobranza")
        self.assertContains(response, "Cartera vencida")


class NoticesAreRenderedOnceTests(PaymentsTestCase):
    """El shell pinta los avisos; las pantallas ya no los repiten."""

    def setUp(self):
        super().setUp()

        self.login(self.make_user("atc1", permissions=["view_charge"]))
        self.notice_url = reverse("customers:use", args=[self.customer.pk])

    def test_a_notice_is_rendered_as_a_dismissible_alert(self):
        response = self.client.get(self.notice_url, follow=True)

        self.assertContains(response, "alert-dismissible")
        self.assertContains(response, "Cliente seleccionado")

    def test_a_notice_appears_a_single_time_on_the_ficha(self):
        response = self.client.get(self.notice_url, follow=True)

        self.assertEqual(
            response.content.decode().count("Cliente seleccionado"), 1
        )

    def test_notices_do_not_pile_up_across_visits(self):
        """Un aviso se consume donde se ve, no espera a la pantalla siguiente."""
        for _ in range(3):
            self.client.get(self.notice_url, follow=True)

        response = self.client.get(self.notice_url, follow=True)

        self.assertEqual(len(response.context["messages"]), 1)


class TheRecordHeaderOffersItsActionsTests(PaymentsTestCase):
    """Las acciones del abonado viven en su encabezado, en todas las pestañas.

    El botón de tres puntos existía antes sin menú detrás: no abría nada. Ahora
    lleva las altas que, si no, obligan a cambiar de pestaña para encontrar su
    botón; y como el encabezado es uno solo, están disponibles se mire el
    abonado desde donde se mire.
    """

    def setUp(self):
        super().setUp()

        self.user = self.make_user(
            "atc1", permissions=["view_charge", "view_payment", "view_receipt"]
        )

    def grant_workorders(self, user):
        from django.contrib.auth.models import Permission

        user.user_permissions.add(
            Permission.objects.get(
                codename="add_workorder", content_type__app_label="work_orders"
            )
        )

    def ficha(self):
        return self.client.get(
            reverse("customers:detail", args=[self.customer.pk])
        )

    def test_the_header_offers_to_print(self):
        self.login(self.user)

        self.assertContains(self.ficha(), "window.print()")

    def test_the_overflow_button_actually_opens_a_menu(self):
        self.login(self.user)

        response = self.ficha()

        self.assertContains(response, 'data-bs-toggle="dropdown"')
        self.assertContains(
            response, reverse("customers:address_create", args=[self.customer.pk])
        )

    def test_the_menu_hides_the_debt_entry_from_who_may_not_issue(self):
        self.login(self.user)

        self.assertNotContains(
            self.ficha(),
            reverse("payments:charge_create", args=[self.customer.pk]),
        )

    def test_the_menu_hides_the_order_entry_from_who_may_not_create(self):
        """No vale con no marcarle el permiso: el rol ATC ya lo concede.

        `work_orders.add_workorder` está en las capacidades mínimas del rol,
        así que para probar que la entrada se esconde hay que usar un rol que
        no la traiga. Marcar solo los permisos y esperar un menú vacío daba un
        falso verde.
        """
        from apps.accounts.models import User as AccountUser

        user = self.make_user(
            "contable1",
            permissions=["view_charge"],
            role=AccountUser.Role.ACCOUNTING,
        )
        self.login(user)

        self.assertNotContains(
            self.ficha(),
            reverse("work_orders:create", args=[self.customer.pk]),
        )

    def test_the_menu_offers_what_the_user_may_do(self):
        user = self.make_user("altas1", permissions=["view_charge", "add_charge"])
        self.grant_workorders(user)
        self.login(user)

        response = self.ficha()

        self.assertContains(
            response, reverse("work_orders:create", args=[self.customer.pk])
        )
        self.assertContains(
            response, reverse("payments:charge_create", args=[self.customer.pk])
        )

    def test_the_actions_travel_with_the_header_to_every_tab(self):
        self.login(self.user)

        for screen in (
            "customers:orders",
            "customers:activity",
            "payments:debt",
            "payments:history",
            "payments:receipts",
        ):
            with self.subTest(screen=screen):
                response = self.client.get(
                    reverse(screen, args=[self.customer.pk])
                )

                self.assertContains(response, "window.print()")
                self.assertContains(response, 'aria-label="Más opciones"')
