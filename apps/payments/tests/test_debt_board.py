"""
El tablero de deuda del abonado: qué columnas lleva, qué dice cada fila y a
dónde lleva.

Lo que se fija aquí es el rediseño de la tabla: la casilla a la izquierda como
única forma de elegir qué cobrar, un estado por fila en lugar de columnas que
repetían lo mismo en cada renglón, y lo pendiente dentro de la tabla -sin
casilla- en vez de en tarjetas encima.
"""

import re
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.template.defaultfilters import date as format_date
from django.urls import reverse
from django.utils import timezone

from apps.payments.board import DATE_FORMAT
from apps.payments.models import Charge, ProposedCharge
from apps.payments.proposals import accept_proposed_charge
from apps.payments.tests.test_proposals import TransferProposalTestCase


def as_shown(day):
    """Una fecha como la escribe la tabla: «14 Sep 2026»."""
    return format_date(day, DATE_FORMAT)


class DebtBoardTestCase(TransferProposalTestCase):
    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()
        self.user = self.make_user(
            "tablero1",
            permissions=[
                "view_charge",
                "add_payment",
                "grant_paymentcommitment",
                "resolve_proposedcharge",
            ],
        )
        self.login(self.user)

    def url(self):
        return reverse("payments:debt", args=[self.customer.pk])

    def body(self):
        return self.client.get(self.url()).content.decode()

    def make_charge(self, **overrides):
        data = {
            "customer": self.customer,
            "concept": Charge.Concept.OTHER,
            "description": "Cargo de prueba",
            "amount": Decimal("30.00"),
            "due_date": self.today + timedelta(days=5),
        }
        data.update(overrides)

        return Charge.objects.create(**data)

    def grant_orders(self):
        self.user.user_permissions.add(
            Permission.objects.get(
                codename="view_workorder",
                content_type__app_label="work_orders",
            )
        )

    def head_of_table(self, body):
        return body[body.index("<thead>") : body.index("</thead>")]


class ColumnasTests(DebtBoardTestCase):
    def columns(self, body):
        return re.findall(r"<th(?: class=\"num\")?>([^<]+)</th>", self.head_of_table(body))

    def test_the_columns_are_the_agreed_ones_in_their_order(self):
        """Abonado, cantidad, moneda y documento repetían lo mismo en cada fila.

        El abonado es el de la ficha, la moneda siempre soles, la cantidad casi
        siempre 1 y el documento siempre vacío: una deuda abierta todavía no
        tiene comprobante. El vencimiento volvió como columna propia, junto al
        monto, porque es lo que se pregunta después de «¿cuánto?».
        """
        self.make_charge()

        self.assertEqual(
            self.columns(self.body()),
            ["Fecha", "Detalle", "Periodo", "Monto", "Vencimiento", "Estado"],
        )

    def test_the_first_column_is_the_checkbox(self):
        charge = self.make_charge()
        body = self.body()

        cabecera = self.head_of_table(body)
        self.assertLess(
            cabecera.index("data-marcar-todas"), cabecera.index("Fecha")
        )

        fila = body[body.index("<tbody>") :]
        self.assertLess(
            fila.index(f'value="{charge.pk}"'),
            fila.index(as_shown(charge.issued_on)),
        )

    def test_the_due_date_has_its_own_column(self):
        vence = self.today + timedelta(days=9)
        self.make_charge(due_date=vence)

        self.assertIn(f'<td class="tc-date">{as_shown(vence)}</td>', self.body())


class DetalleTests(DebtBoardTestCase):
    """El detalle en dos palabras, y la descripción entera a un pase del cursor."""

    def detail_of(self, charge):
        response = self.client.get(self.url())

        return next(
            row for row in response.context["page_obj"] if row.charge == charge
        )

    def test_a_long_description_keeps_its_name_and_drops_the_rest(self):
        charge = self.make_charge(
            description="AVERÍA INTERNET - RESPONSABILIDAD DEL CLIENTE"
        )
        fila = self.detail_of(charge)

        self.assertEqual(fila.detail, "Avería internet")
        self.assertIn("RESPONSABILIDAD DEL CLIENTE", fila.full_detail)

    def test_the_connecting_words_do_not_use_up_the_two_words(self):
        charge = self.make_charge(description="ALQUILER DE DECODIFICADOR")

        self.assertEqual(self.detail_of(charge).detail, "Alquiler decodificador")

    def test_the_monthly_fee_of_the_cycle_shows_the_contracted_plan(self):
        """La que emite el sistema se nombra por el plan, entero.

        Va atada a la suscripción y sin concepto de catálogo; su descripción
        guarda el plan del mes facturado. Las siglas y cifras se quedan en
        mayúsculas.
        """
        charge = self.make_charge(
            concept=Charge.Concept.MONTHLY,
            subscription=self.subscription,
            description="PLAN DUO ESTANDAR 600MG - 2026",
        )

        self.assertEqual(
            self.detail_of(charge).detail, "Plan DUO estandar 600MG - 2026"
        )

    def test_a_plan_written_with_care_is_left_as_it_is(self):
        """«Mbps» pasado a minúsculas dejaría de ser la unidad."""
        charge = self.make_charge(
            concept=Charge.Concept.MONTHLY,
            subscription=self.subscription,
            description="Internet 1000 Mbps - Estandar 2025",
        )

        self.assertEqual(
            self.detail_of(charge).detail, "Internet 1000 Mbps - Estandar 2025"
        )

    def manual_monthly_fee(self, **fields):
        """Una mensualidad puesta a mano: concepto de catálogo, sin suscripción."""
        from apps.payments.models import ChargeConcept

        # El que siembran las migraciones, el mismo que ofrece el formulario.
        concepto, _ = ChargeConcept.objects.get_or_create(
            code="mensualidad",
            defaults={"name": "MENSUALIDAD", "family": Charge.Concept.MONTHLY},
        )
        return self.make_charge(
            concept=Charge.Concept.MONTHLY,
            concept_item=concepto,
            description="MENSUALIDAD",
            **fields,
        )

    def test_an_automatic_fee_put_by_hand_shows_the_active_plan(self):
        """«Actualizar automáticamente»: sigue al plan, y lo nombra.

        No tiene suscripción; su plan es el de la suscripción activa, el
        mismo que le dio el monto al emitirla.
        """
        charge = self.manual_monthly_fee(auto_update=True)

        self.assertEqual(self.detail_of(charge).detail, self.subscription.plan.name)

    def test_a_fixed_fee_put_by_hand_is_called_so(self):
        """Un monto pactado que no sigue al plan no dice un plan."""
        charge = self.manual_monthly_fee(auto_update=False)

        self.assertEqual(self.detail_of(charge).detail, "Mensualidad")

    def test_without_an_active_plan_it_is_called_so(self):
        from apps.services.models import Subscription

        Subscription.objects.update(status=Subscription.Status.SUSPENDED)
        charge = self.manual_monthly_fee(auto_update=True)

        self.assertEqual(self.detail_of(charge).detail, "Mensualidad")

    def test_the_row_carries_no_second_line(self):
        """Todas las filas miden lo mismo: nada debajo del detalle."""
        self.make_charge(description="AVERÍA INTERNET - RESPONSABILIDAD DEL CLIENTE")
        body = self.body()
        cuerpo = body[body.index("<tbody>") : body.index("</tbody>")]

        self.assertNotIn("tc-sub", cuerpo)
        self.assertIn('title="AVERÍA INTERNET - RESPONSABILIDAD DEL CLIENTE"', cuerpo)


class EstadoTests(DebtBoardTestCase):
    """Tres estados: pendiente en ámbar, compromiso en morado, vencido en rojo."""

    def row_of(self, charge):
        response = self.client.get(self.url())

        return next(
            row for row in response.context["page_obj"] if row.charge == charge
        )

    def test_an_overdue_charge_is_overdue_in_red(self):
        fila = self.row_of(self.make_charge(due_date=self.today - timedelta(days=3)))

        self.assertEqual((fila.status, fila.tone), ("Vencido", "danger"))

    def test_a_charge_not_yet_due_is_pending_in_amber(self):
        fila = self.row_of(self.make_charge(due_date=self.today + timedelta(days=3)))

        self.assertEqual((fila.status, fila.tone), ("Pendiente", "warning"))

    def test_a_partly_paid_charge_is_still_pending_and_says_how_much(self):
        """El pago parcial no es un estado más: va en el rótulo emergente."""
        fila = self.row_of(self.make_charge(
            due_date=self.today + timedelta(days=3),
            status=Charge.Status.PARTIALLY_PAID,
        ))

        self.assertEqual(fila.status, "Pendiente")
        self.assertIn("Pago parcial", fila.status_title)

    def test_a_committed_charge_is_purple(self):
        from apps.payments.services import grant_commitment

        charge = self.make_charge(due_date=self.today - timedelta(days=3))
        grant_commitment(
            customer=self.customer,
            charges=[charge],
            user=self.cashier,
            committed_date=self.today + timedelta(days=7),
            reason="Cobra el viernes.",
        )

        fila = self.row_of(charge)

        self.assertEqual((fila.status, fila.tone), ("Compromiso", "violet"))


class LoPendienteTests(DebtBoardTestCase):
    def setUp(self):
        super().setUp()

        self.order = self.make_transfer_order()
        self.proposal = ProposedCharge.objects.get(work_order=self.order)
        self.charge = self.make_charge()

    def test_the_pending_row_goes_first_and_cannot_be_marked(self):
        """Primero lo que espera una decisión, y sin casilla que marcar."""
        response = self.client.get(self.url())
        filas = list(response.context["page_obj"])

        self.assertEqual(filas[0].status, "Pendiente")
        self.assertIsNone(filas[0].charge)
        self.assertEqual(filas[1].charge, self.charge)

        # Casillas de verdad, con su valor: el guion de la página también
        # nombra `input[name="charges"]` y no es una casilla.
        body = response.content.decode()
        self.assertEqual(len(re.findall(r'name="charges"\s+value=', body)), 1)

    def test_the_footer_counts_the_pending_rows_too(self):
        """El pie cuenta las filas que se ven, no solo los cargos."""
        self.assertIn("2 registros", self.body())

    def test_the_pending_amount_does_not_add_to_the_debt(self):
        response = self.client.get(self.url())

        self.assertEqual(response.context["debt"]["total"], self.charge.amount)


class ElEstadoAbreElDocumentoTests(DebtBoardTestCase):
    """Lo que lleva a otra pantalla es el estado, no la fila entera.

    La fila se sombrea y se marca; un clic en cualquier parte de ella que
    además saltara de pantalla se llevaba al operador cuando solo quería
    marcarla.
    """

    def setUp(self):
        super().setUp()

        self.order = self.make_transfer_order()
        self.proposal = ProposedCharge.objects.get(work_order=self.order)

    def order_url(self):
        return reverse("work_orders:detail", args=[self.order.pk])

    def test_a_charge_born_from_an_order_opens_that_order(self):
        accept_proposed_charge(
            proposal=self.proposal,
            user=self.user,
            amount=Decimal("50.00"),
            due_date=self.today + timedelta(days=5),
        )
        self.grant_orders()

        body = self.body()

        self.assertRegex(
            body, r'<a class="status-\w+"\s+href="%s"' % re.escape(self.order_url())
        )
        self.assertIn(self.order.order_number, body)

    def test_without_access_to_orders_the_row_does_not_lead_there(self):
        accept_proposed_charge(
            proposal=self.proposal,
            user=self.user,
            amount=Decimal("50.00"),
            due_date=self.today + timedelta(days=5),
        )

        body = self.body()

        self.assertNotIn(self.order_url(), body)
        self.assertNotIn('<a class="status-', body)

    def test_a_charge_without_an_order_has_nowhere_to_go(self):
        ProposedCharge.objects.all().delete()
        self.make_charge()
        self.grant_orders()

        body = self.body()

        self.assertIn('<span class="status-', body)
        self.assertNotIn('<a class="status-', body)

    def test_the_row_itself_does_not_open(self):
        accept_proposed_charge(
            proposal=self.proposal,
            user=self.user,
            amount=Decimal("50.00"),
            due_date=self.today + timedelta(days=5),
        )
        self.grant_orders()

        self.assertNotIn("data-href", self.body())


class PeriodoTests(DebtBoardTestCase):
    """El periodo en el mismo idioma que las fechas, y corto."""

    def period_of(self, **fields):
        charge = self.make_charge(**fields)
        response = self.client.get(self.url())

        return next(
            row.period for row in response.context["page_obj"]
            if row.charge == charge
        )

    def test_a_calendar_month_reads_as_the_month(self):
        from datetime import date

        self.assertEqual(
            self.period_of(period=date(2026, 9, 1), period_end=date(2026, 9, 30)),
            format_date(date(2026, 9, 1), "M Y"),
        )

    def test_a_period_across_months_reads_as_a_range(self):
        from datetime import date

        periodo = self.period_of(
            period=date(2026, 9, 15), period_end=date(2026, 10, 14)
        )

        self.assertEqual(
            periodo,
            f"{format_date(date(2026, 9, 15), 'j M')} – {as_shown(date(2026, 10, 14))}",
        )


class BotonesTests(DebtBoardTestCase):
    def test_collecting_and_committing_act_on_the_selection(self):
        """Los dos botones que actúan sobre lo marcado lo declaran.

        El guion los apaga mientras no haya nada marcado. Se marca en el
        botón y no se apaga desde el servidor para que, sin guion, sigan
        funcionando y el servidor devuelva el aviso.
        """
        self.make_charge()
        body = self.body()

        self.assertIn('data-exige-seleccion="cobrar"', body)
        self.assertIn('data-exige-seleccion="aplazar"', body)
        self.assertNotRegex(body, r"<button[^>]*data-exige-seleccion[^>]*disabled")
