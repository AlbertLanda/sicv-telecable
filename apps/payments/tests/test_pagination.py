"""
Las tablas del abonado se leen de quince en quince.

Un mismo tamaño en todas: cambiar de pestaña no debería cambiar cuánto se ve
de golpe, y «página 2» tiene que significar lo mismo en cada una. La tabla de
deuda es la excepción parcial -conserva un selector de tamaño- porque
«Cobrar» y «Compromiso» actúan sobre las filas marcadas y la marca no cruza
de página.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from apps.customers.dashboard_views import ROWS_PER_PAGE
from apps.payments.models import Charge
from apps.payments.tests.base import PaymentsTestCase
from apps.work_orders.models import OrderType, WorkOrder


ROWS = ROWS_PER_PAGE


class DebtTablePaginatesTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.user = self.make_user("consulta1", permissions=["view_charge"])
        self.login(self.user)

        today = timezone.localdate()
        for offset in range(ROWS + 3):
            Charge.objects.create(
                customer=self.customer,
                concept=Charge.Concept.OTHER,
                description="Cargo %s" % offset,
                amount=Decimal("10.00"),
                due_date=today + timedelta(days=offset),
            )

    def url(self):
        return reverse("payments:debt", args=[self.customer.pk])

    def test_the_first_page_holds_fifteen_rows(self):
        response = self.client.get(self.url())

        self.assertEqual(len(response.context["page_obj"].object_list), ROWS)
        self.assertTrue(response.context["is_paginated"])

    def test_the_rest_spills_into_the_next_page(self):
        response = self.client.get(self.url(), {"page": "2"})

        self.assertEqual(len(response.context["page_obj"].object_list), 3)

    def test_the_totals_keep_counting_the_whole_debt(self):
        """El resumen no puede leer de la página.

        Si lo hiciera diría «15 deudas abiertas» cuando el abonado tiene 18, y
        el operador cerraría la atención creyendo la cuenta más limpia de lo
        que está.
        """
        response = self.client.get(self.url())

        self.assertEqual(response.context["debt"]["count"], ROWS + 3)
        self.assertEqual(
            response.context["debt"]["total"], Decimal("10.00") * (ROWS + 3)
        )

    def test_changing_page_keeps_the_chosen_size(self):
        """El paginador conserva el resto de la URL.

        Sin eso, pasar de página devolvería al operador al tamaño por defecto
        justo después de haber pedido ver más filas.
        """
        response = self.client.get(self.url(), {"filas": "30", "page": "1"})

        self.assertEqual(response.context["page_size"], 30)
        self.assertFalse(response.context["is_paginated"])


class OrdersTablePaginatesTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.user = self.make_user("consulta1", permissions=[])
        self.user.user_permissions.add(
            self.workorder_permission("view_workorder")
        )
        self.login(self.user)

        order_type = OrderType.objects.create(code="INST", name="Instalación")

        for number in range(ROWS + 2):
            WorkOrder.objects.create(
                order_number="OT-%04d" % number,
                subscription=self.subscription,
                order_type=order_type,
                branch=self.branch,
                zone=self.zone,
                status=WorkOrder.Status.PENDING,
                created_by=self.user,
            )

    def workorder_permission(self, codename):
        from django.contrib.auth.models import Permission

        return Permission.objects.get(
            codename=codename, content_type__app_label="work_orders"
        )

    def test_the_first_page_holds_fifteen_rows(self):
        response = self.client.get(
            reverse("customers:orders", args=[self.customer.pk])
        )

        self.assertEqual(len(response.context["page_obj"].object_list), ROWS)
        self.assertTrue(response.context["is_paginated"])

    def test_the_rest_spills_into_the_next_page(self):
        response = self.client.get(
            reverse("customers:orders", args=[self.customer.pk]),
            {"page": "2"},
        )

        self.assertEqual(len(response.context["page_obj"].object_list), 2)


class EveryTableAgreesOnTheSizeTests(PaymentsTestCase):
    """Historial y comprobantes usan el mismo tamaño que el resto."""

    def test_the_payment_screens_page_in_the_same_size(self):
        from apps.payments.views import (
            CustomerPaymentHistoryView,
            CustomerReceiptsView,
        )

        self.assertEqual(CustomerPaymentHistoryView.paginate_by, ROWS)
        self.assertEqual(CustomerReceiptsView.paginate_by, ROWS)

    def test_the_debt_board_defaults_to_the_same_size(self):
        from apps.payments.views import CustomerDebtView

        self.assertEqual(CustomerDebtView.DEFAULT_PAGE_SIZE, ROWS)


class TheFooterShowsEvenWhenEverythingFitsTests(PaymentsTestCase):
    """Una tabla sin pie no dice si lo que se ve es todo o es el principio.

    Con doce órdenes no había paginador, y el operador no tenía forma de
    distinguir «doce órdenes» de «las doce primeras».
    """

    def setUp(self):
        super().setUp()

        self.user = self.make_user("consulta1", permissions=[])
        self.user.user_permissions.add(
            Permission.objects.get(
                codename="view_workorder", content_type__app_label="work_orders"
            )
        )
        self.login(self.user)

        order_type = OrderType.objects.create(code="INST", name="Instalación")

        for number in range(12):
            WorkOrder.objects.create(
                order_number="OT-%04d" % number,
                subscription=self.subscription,
                order_type=order_type,
                branch=self.branch,
                zone=self.zone,
                status=WorkOrder.Status.PENDING,
                created_by=self.user,
            )

    def test_the_footer_reports_how_many_there_are(self):
        response = self.client.get(
            reverse("customers:orders", args=[self.customer.pk])
        )

        self.assertFalse(response.context["is_paginated"])
        self.assertContains(response, "12 registros")
        self.assertContains(response, "página 1 de 1")

    def test_an_empty_table_has_no_footer_to_show(self):
        """Sin filas el pie sobra: el estado vacío ya lo dice todo."""
        WorkOrder.objects.all().delete()

        response = self.client.get(
            reverse("customers:orders", args=[self.customer.pk])
        )

        self.assertNotContains(response, "página 1 de 1")
        self.assertContains(response, "Sin órdenes registradas.")


class TheFooterKeepsTheRestOfTheUrlTests(PaymentsTestCase):
    """Pasar de página no puede deshacer lo que el operador ya eligió."""

    def setUp(self):
        super().setUp()

        self.login(self.make_user("consulta1", permissions=["view_charge"]))

        today = timezone.localdate()
        for offset in range(35):
            Charge.objects.create(
                customer=self.customer,
                concept=Charge.Concept.OTHER,
                description="Cargo %s" % offset,
                amount=Decimal("10.00"),
                due_date=today + timedelta(days=offset),
            )

    def test_the_next_page_link_carries_the_chosen_size(self):
        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk]), {"filas": "30"}
        )
        body = response.content.decode()

        self.assertIn("filas=30&amp;page=2", body)
