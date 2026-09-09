"""
Botón «Nuevo» del tablero de deuda y cobro desde una fila.

Lo que se fija aquí es la frontera entre lo automático y lo manual: el ciclo
emite la mensualidad solo desde el plan contratado, y la ventanilla puede
emitir cualquier concepto -mensualidad incluida- para cubrir lo que ese ciclo
no alcanzó. Lo que evita cobrar dos veces el mes de una suscripción es la
restricción única de (suscripción, periodo), no que la pantalla esconda el
concepto.
"""

import re
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.payments.models import Charge, Payment
from apps.payments.services import create_manual_charge, register_payment
from apps.payments.tests.base import PaymentsTestCase


class ManualChargeServiceTests(PaymentsTestCase):
    def test_it_issues_a_charge_that_the_cycle_does_not_generate(self):
        charge = create_manual_charge(
            customer=self.customer,
            concept=Charge.Concept.REACTIVATION,
            description="Reconexión por corte",
            amount=Decimal("20.00"),
            due_date=date(2026, 10, 15),
        )

        self.assertEqual(charge.customer, self.customer)
        self.assertEqual(charge.status, Charge.Status.PENDING)
        self.assertEqual(charge.balance, Decimal("20.00"))
        self.assertIsNone(charge.subscription)

    def test_a_manual_monthly_charge_takes_the_period_from_its_date(self):
        """El formulario no pide el periodo: la fecha de emisión ya lo dice.

        El modelo exige que una mensualidad tenga su mes, y el servicio lo
        deriva en vez de rechazar el cargo: pedirlo aparte obligaría al
        operador a teclear dos veces la misma información.
        """
        charge = create_manual_charge(
            customer=self.customer,
            concept=Charge.Concept.MONTHLY,
            description="Mensualidad emitida a mano",
            amount=Decimal("80.00"),
            due_date=date(2026, 10, 31),
            issued_on=date(2026, 10, 7),
        )

        self.assertEqual(charge.period, date(2026, 10, 1))
        self.assertEqual(charge.period_end, date(2026, 10, 31))

    def test_the_same_month_still_cannot_be_charged_twice(self):
        """Lo que protege contra duplicar la mensualidad es la restricción.

        Emitir una a mano está permitido -el sistema anterior lo permite-, y
        lo que evita cobrar dos veces el mes de una suscripción es el índice
        único de (suscripción, periodo), no que la pantalla lo esconda.

        Llega como ValidationError y no como IntegrityError porque
        `full_clean()` valida la restricción antes de tocar la base: así el
        operador lee un mensaje en la pantalla en vez de recibir un error 500.
        """
        create_manual_charge(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            description="Mensualidad de octubre",
            amount=Decimal("80.00"),
            due_date=date(2026, 10, 31),
            issued_on=date(2026, 10, 7),
        )

        with self.assertRaises(ValidationError):
            create_manual_charge(
                customer=self.customer,
                subscription=self.subscription,
                concept=Charge.Concept.MONTHLY,
                description="Mensualidad repetida",
                amount=Decimal("80.00"),
                due_date=date(2026, 10, 31),
                issued_on=date(2026, 10, 20),
            )

    def test_a_discount_without_its_deadline_is_rejected(self):
        with self.assertRaises(ValidationError):
            create_manual_charge(
                customer=self.customer,
                concept=Charge.Concept.OTHER,
                description="Cargo con descuento suelto",
                amount=Decimal("50.00"),
                due_date=date(2026, 10, 15),
                early_discount=Decimal("5.00"),
            )


class ManualChargeWebTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()
        self.viewer = self.make_user("consulta1", permissions=["view_charge"])
        self.issuer = self.make_user(
            "emisor1", permissions=["view_charge", "add_charge"]
        )

    def url(self):
        return reverse("payments:charge_create", args=[self.customer.pk])

    def test_viewing_the_debt_does_not_grant_issuing_it(self):
        self.login(self.viewer)

        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_the_board_hides_the_new_button_without_permission(self):
        self.login(self.viewer)

        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertFalse(response.context["can_create_charge"])
        self.assertNotContains(response, self.url())

    def test_the_board_offers_the_new_button_to_who_may_issue(self):
        self.login(self.issuer)

        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertTrue(response.context["can_create_charge"])
        self.assertContains(response, self.url())

    def test_the_form_offers_every_concept_including_the_monthly_one(self):
        """La ventanilla puede emitir cualquier concepto, mensualidad incluida.

        El ciclo automático sigue emitiéndola sola; poder emitirla a mano
        cubre los casos que ese ciclo no alcanzó, y la restricción única de
        (suscripción, periodo) evita que se cobre dos veces.
        """
        self.login(self.issuer)

        response = self.client.get(self.url())
        offered = [
            value for value, _ in response.context["form"].fields["concept"].choices
        ]

        self.assertIn(Charge.Concept.MONTHLY, offered)
        self.assertIn(Charge.Concept.REACTIVATION, offered)

    def test_a_manual_charge_is_issued_and_appears_in_the_debt(self):
        self.login(self.issuer)

        response = self.client.post(
            self.url(),
            {
                "concept": Charge.Concept.REACTIVATION,
                "description": "Reconexión por corte",
                "amount": "20.00",
                "due_date": (self.today + timedelta(days=10)).isoformat(),
                "early_discount": "",
                "discount_deadline": "",
                "subscription": "",
            },
        )

        charge = Charge.objects.get()

        self.assertRedirects(
            response, reverse("payments:debt", args=[self.customer.pk])
        )
        self.assertEqual(charge.description, "Reconexión por corte")
        self.assertEqual(charge.amount, Decimal("20.00"))

    def test_only_the_subscriptions_of_this_customer_are_offered(self):
        """Nadie debe poder colgarle un cargo del servicio de otra persona."""
        from apps.customers.models import Customer, CustomerAddress
        from apps.services.models import Subscription

        other = Customer.objects.create(
            code="CLI002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="10101010",
            first_name="Ana",
            paternal_surname="Lopez",
        )
        other_address = CustomerAddress.objects.create(
            customer=other,
            zone=self.zone,
            address="Jr. Union 100",
            district="Chachapoyas",
            is_primary=True,
        )
        foreign_subscription = Subscription.objects.create(
            customer=other,
            address=other_address,
            service_type=self.service_type,
            plan=self.plan,
            billing_policy=self.policy,
            status=Subscription.Status.ACTIVE,
        )

        self.login(self.issuer)
        response = self.client.get(self.url())
        offered = response.context["form"].fields["subscription"].queryset

        self.assertIn(self.subscription, offered)
        self.assertNotIn(foreign_subscription, offered)

    def test_an_invalid_amount_does_not_create_anything(self):
        self.login(self.issuer)

        response = self.client.post(
            self.url(),
            {
                "concept": Charge.Concept.OTHER,
                "description": "Cargo sin monto",
                "amount": "0",
                "due_date": (self.today + timedelta(days=5)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Charge.objects.exists())


class ChargeSelectionTests(PaymentsTestCase):
    """Cobrar y comprometer se arman con las filas marcadas del tablero."""

    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()

        self.old = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo antiguo",
            amount=Decimal("80.00"),
            due_date=self.today - timedelta(days=20),
        )
        self.recent = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo reciente",
            amount=Decimal("50.00"),
            due_date=self.today + timedelta(days=10),
        )

        self.cashier_user = self.make_user(
            "ventanilla1", permissions=["view_charge", "add_payment"]
        )

    def register_url(self):
        return reverse("payments:register", args=[self.customer.pk])

    def test_every_row_carries_its_own_checkbox(self):
        """Cada deuda trae su casilla, que es como se elige qué cobrar.

        Se cuentan etiquetas `input` y no apariciones del texto `name="charges"`:
        el guion que avisa de que no hay nada marcado busca esas casillas por
        selector, así que la cadena suelta también sale en el script y contarla
        daba dos de más.
        """
        self.login(self.cashier_user)

        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )
        html = response.content.decode()
        checkboxes = re.findall(r'<input[^>]*name="charges"[^>]*>', html)

        self.assertEqual(len(checkboxes), 2)
        self.assertIn('value="%s"' % self.old.pk, html)
        self.assertIn('value="%s"' % self.recent.pk, html)

    def test_the_selected_rows_arrive_at_the_charging_screen(self):
        """Lo marcado en el tablero es lo que se cobra.

        El monto llega ya sumado para que el operador no recalcule a mano lo
        que las filas acababan de mostrar.
        """
        self.login(self.cashier_user)

        response = self.client.get(
            self.register_url(), {"charges": [self.recent.pk]}
        )

        self.assertEqual(response.context["selected_charges"], [self.recent])
        self.assertEqual(response.context["selected_total"], Decimal("50.00"))
        self.assertEqual(
            response.context["form"].initial["amount"], Decimal("50.00")
        )

    def test_several_selected_rows_are_summed(self):
        self.login(self.cashier_user)

        response = self.client.get(
            self.register_url(),
            {"charges": [self.old.pk, self.recent.pk]},
        )

        self.assertEqual(response.context["selected_total"], Decimal("130.00"))

    def test_charging_the_selection_pays_exactly_those_rows(self):
        self.login(self.cashier_user)

        self.client.post(
            self.register_url(),
            {
                "amount": "50.00",
                "method": Payment.Method.CASH,
                "charges": [self.recent.pk],
            },
        )

        self.old.refresh_from_db()
        self.recent.refresh_from_db()

        self.assertEqual(self.recent.status, Charge.Status.PAID)
        self.assertEqual(self.old.status, Charge.Status.PENDING)

    def test_without_a_selection_nothing_is_preselected(self):
        self.login(self.cashier_user)

        response = self.client.get(self.register_url())

        self.assertEqual(response.context["selected_charges"], [])
        self.assertEqual(response.context["selected_total"], Decimal("0.00"))

    def test_a_non_numeric_id_is_ignored(self):
        self.login(self.cashier_user)

        response = self.client.get(self.register_url(), {"charges": "abc"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_charges"], [])

    def test_an_unknown_id_is_ignored(self):
        self.login(self.cashier_user)

        response = self.client.get(self.register_url(), {"charges": "999999"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_charges"], [])

    def test_a_charge_of_another_customer_is_not_selected(self):
        """El enlace no manda: los ids se filtran contra la deuda del abonado.

        Sin ese filtro, un id ajeno pegado en la URL entraria al cobro de
        este cliente.
        """
        from apps.customers.models import Customer

        other = Customer.objects.create(
            code="CLI002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="10101010",
            first_name="Ana",
            paternal_surname="Lopez",
        )
        foreign = Charge.objects.create(
            customer=other,
            concept=Charge.Concept.OTHER,
            description="Cargo ajeno",
            amount=Decimal("30.00"),
            due_date=self.today,
        )

        self.login(self.cashier_user)
        response = self.client.get(
            self.register_url(), {"charges": [foreign.pk]}
        )

        self.assertEqual(response.context["selected_charges"], [])

    def test_an_already_paid_charge_is_not_selected(self):
        from apps.payments.services import register_payment

        register_payment(
            customer=self.customer,
            amount=Decimal("50.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.recent, Decimal("50.00"))],
        )

        self.login(self.cashier_user)
        response = self.client.get(
            self.register_url(), {"charges": [self.recent.pk]}
        )

        self.assertEqual(response.context["selected_charges"], [])


class EarlyDiscountOnAManualChargeTests(PaymentsTestCase):
    """El pronto pago de una deuda emitida a mano.

    El servicio y la vista ya lo aceptaban y el formulario declaraba los dos
    campos, pero la pantalla no los pintaba: viajaban siempre vacíos, así que
    la ventanilla no tenía forma de conceder un descuento al emitir.
    """

    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()
        self.issuer = self.make_user(
            "emisor1", permissions=["view_charge", "add_charge"]
        )
        self.login(self.issuer)

    def url(self):
        return reverse("payments:charge_create", args=[self.customer.pk])

    def payload(self, **overrides):
        data = {
            "concept": Charge.Concept.REACTIVATION,
            "description": "Reconexión por corte",
            "amount": "20.00",
            "due_date": (self.today + timedelta(days=10)).isoformat(),
            "early_discount": "",
            "discount_deadline": "",
            "subscription": "",
        }
        data.update(overrides)

        return data

    def test_the_screen_offers_both_fields(self):
        response = self.client.get(self.url())

        self.assertContains(response, 'name="early_discount"')
        self.assertContains(response, 'name="discount_deadline"')

    def test_a_discount_with_its_deadline_reaches_the_charge(self):
        deadline = self.today + timedelta(days=5)

        self.client.post(
            self.url(),
            self.payload(
                early_discount="3.00",
                discount_deadline=deadline.isoformat(),
            ),
        )

        charge = Charge.objects.get()

        self.assertEqual(charge.early_discount, Decimal("3.00"))
        self.assertEqual(charge.discount_deadline, deadline)

    def test_a_discount_without_its_deadline_is_rejected_on_screen(self):
        """Sin plazo sería un descuento permanente, que es otra cosa.

        Llega como error del formulario y no como un 500: el operador lee qué
        le falta en la misma pantalla en vez de perder lo que ya escribió.
        """
        response = self.client.post(
            self.url(), self.payload(early_discount="3.00")
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Charge.objects.exists())
        self.assertTrue(response.context["form"].errors)

    def test_without_a_discount_the_charge_is_issued_as_before(self):
        self.client.post(self.url(), self.payload())

        charge = Charge.objects.get()

        self.assertEqual(charge.early_discount, Decimal("0"))
        self.assertIsNone(charge.discount_deadline)


class TheSubscriptionIsNamedByItsServiceTests(PaymentsTestCase):
    """Cómo se lee una suscripción en el desplegable de la nueva deuda.

    `Subscription.__str__` antepone el nombre del cliente. Aquí sobra -la
    pantalla ya es la de ese abonado- y ocupaba el ancho del campo hasta
    empujar el plan, que es lo único que distingue una suscripción de otra,
    fuera de la vista.
    """

    def setUp(self):
        super().setUp()

        self.issuer = self.make_user(
            "emisor1", permissions=["view_charge", "add_charge"]
        )
        self.login(self.issuer)

    def body(self):
        response = self.client.get(
            reverse("payments:charge_create", args=[self.customer.pk])
        )

        return response.content.decode()

    def test_the_option_leads_with_the_service_and_its_plan(self):
        self.assertInHTML(
            '<option value="%s">#1 · Internet · Fibra 100 Mbps</option>'
            % self.subscription.pk,
            self.body(),
            count=1,
        )

    def test_the_option_does_not_repeat_the_customer_name(self):
        self.assertNotIn("Juan Pérez Ramos - Fibra 100 Mbps", self.body())

    def test_a_subscription_that_is_not_active_says_so(self):
        """Una activa no necesita anunciarlo; una suspendida cambia la charla."""
        from apps.services.models import Subscription

        suspended = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            billing_policy=self.policy,
            status=Subscription.Status.SUSPENDED,
            service_number=2,
            base_monthly_fee=80,
        )

        self.assertInHTML(
            '<option value="%s">#2 · Internet · Fibra 100 Mbps (Suspendido)</option>'
            % suspended.pk,
            self.body(),
            count=1,
        )

    def test_the_empty_option_says_what_leaving_it_blank_means(self):
        """«---------» no dice nada; el campo es opcional y hay que verlo."""
        self.assertIn("Sin servicio asociado", self.body())


class ADebtCannotBeNegativeTests(PaymentsTestCase):
    """Un cargo en negativo no existe.

    Lo que se le devuelve al abonado es un pago o una anulación, no una deuda
    al revés: un monto negativo restaría del total adeudado y dejaría la
    cuenta diciendo que debe menos de lo que debe. Se frena en las tres capas
    porque el cargo entra por tres puertas -la pantalla, el servicio manual y
    el ciclo mensual- y solo la primera tiene formulario.
    """

    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()
        self.issuer = self.make_user(
            "emisor1", permissions=["view_charge", "add_charge"]
        )

    def payload(self, **overrides):
        data = {
            "concept": Charge.Concept.REACTIVATION,
            "description": "Nota de ajuste",
            "amount": "20.00",
            "due_date": (self.today + timedelta(days=10)).isoformat(),
            "early_discount": "",
            "discount_deadline": "",
            "subscription": "",
        }
        data.update(overrides)

        return data

    # -- La pantalla -------------------------------------------------

    def test_the_screen_rejects_a_negative_amount(self):
        self.login(self.issuer)

        response = self.client.post(
            reverse("payments:charge_create", args=[self.customer.pk]),
            self.payload(amount="-0.08"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Charge.objects.exists())
        self.assertIn("amount", response.context["form"].errors)

    def test_the_screen_rejects_a_zero_amount(self):
        """Cero tampoco: una deuda de cero no reclama nada."""
        self.login(self.issuer)

        response = self.client.post(
            reverse("payments:charge_create", args=[self.customer.pk]),
            self.payload(amount="0"),
        )

        self.assertFalse(Charge.objects.exists())
        self.assertIn("amount", response.context["form"].errors)

    def test_the_screen_rejects_a_negative_quantity(self):
        self.login(self.issuer)

        response = self.client.post(
            reverse("payments:charge_create", args=[self.customer.pk]),
            self.payload(quantity="-2"),
        )

        self.assertFalse(Charge.objects.exists())
        self.assertIn("quantity", response.context["form"].errors)

    def test_the_screen_rejects_a_negative_discount(self):
        """Un descuento en negativo subiría lo que el abonado debe."""
        self.login(self.issuer)

        response = self.client.post(
            reverse("payments:charge_create", args=[self.customer.pk]),
            self.payload(
                early_discount="-5.00",
                discount_deadline=(self.today + timedelta(days=3)).isoformat(),
            ),
        )

        self.assertFalse(Charge.objects.exists())
        self.assertIn("early_discount", response.context["form"].errors)

    def test_the_field_tells_the_browser_where_the_floor_is(self):
        """La flecha del spinner es por donde se llega al negativo sin querer."""
        self.login(self.issuer)

        response = self.client.get(
            reverse("payments:charge_create", args=[self.customer.pk])
        )
        body = response.content.decode()

        self.assertIn('min="0.01"', body)

    # -- El servicio -------------------------------------------------

    def test_the_service_rejects_it_too(self):
        """La pantalla no es la unica puerta: el servicio se llama directo."""
        with self.assertRaises(ValidationError):
            create_manual_charge(
                customer=self.customer,
                concept=Charge.Concept.OTHER,
                description="Ajuste al reves",
                amount=Decimal("-30.00"),
                due_date=self.today + timedelta(days=5),
            )

        self.assertFalse(Charge.objects.exists())

    def test_a_valid_amount_still_goes_through(self):
        charge = create_manual_charge(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Ajuste normal",
            amount=Decimal("30.00"),
            due_date=self.today + timedelta(days=5),
        )

        self.assertEqual(charge.amount, Decimal("30.00"))

    # -- El modelo ---------------------------------------------------

    def test_the_model_is_the_last_defence(self):
        charge = Charge(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo al reves",
            amount=Decimal("-1.00"),
            due_date=self.today,
        )

        with self.assertRaises(ValidationError) as caught:
            charge.full_clean()

        self.assertIn("amount", caught.exception.error_dict)


class ActingWithoutSelectingAnythingTests(PaymentsTestCase):
    """«Cobrar» y «Compromiso» actúan sobre lo marcado.

    Sin nada marcado, la pantalla de destino se abría en blanco y el operador
    tenía que deducir que el problema estaba en el tablero que acababa de
    dejar atrás. Ahora vuelve al tablero con el aviso, sin perder de vista las
    deudas que tenía que marcar.
    """

    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()
        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo pendiente",
            amount=Decimal("50.00"),
            due_date=self.today + timedelta(days=10),
        )

        self.user = self.make_user(
            "ventanilla1",
            permissions=["view_charge", "add_payment", "grant_paymentcommitment"],
        )
        self.login(self.user)

    def board_url(self):
        return reverse("payments:debt", args=[self.customer.pk])

    # -- Cobro -------------------------------------------------------

    def test_collecting_with_nothing_marked_returns_to_the_board(self):
        response = self.client.get(
            reverse("payments:register", args=[self.customer.pk]),
            {"origen": "tablero"},
        )

        self.assertRedirects(response, self.board_url())

    def test_it_says_what_was_missing(self):
        response = self.client.get(
            reverse("payments:register", args=[self.customer.pk]),
            {"origen": "tablero"},
            follow=True,
        )

        self.assertContains(response, "Marque la deuda que va a cobrar.")

    def test_with_a_row_marked_it_opens_the_charging_screen(self):
        response = self.client.get(
            reverse("payments:register", args=[self.customer.pk]),
            {"origen": "tablero", "charges": self.charge.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_charges"], [self.charge])

    def test_a_charge_that_is_no_longer_open_counts_as_nothing_marked(self):
        """Marcar algo que otro cajero acaba de cobrar no es marcar."""
        register_payment(
            customer=self.customer,
            amount=Decimal("50.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.user,
            allocations=[(self.charge, Decimal("50.00"))],
        )

        response = self.client.get(
            reverse("payments:register", args=[self.customer.pk]),
            {"origen": "tablero", "charges": self.charge.pk},
        )

        self.assertRedirects(response, self.board_url())

    # -- Compromiso --------------------------------------------------

    def test_a_commitment_with_nothing_marked_returns_too(self):
        response = self.client.get(
            reverse("payments:commitment_create", args=[self.customer.pk]),
            {"origen": "tablero"},
            follow=True,
        )

        self.assertContains(
            response, "Marque las deudas que entran en el compromiso."
        )

    def test_a_commitment_with_a_row_marked_opens(self):
        response = self.client.get(
            reverse("payments:commitment_create", args=[self.customer.pk]),
            {"origen": "tablero", "charges": self.charge.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_charges"], [self.charge])

    # -- El adelanto sigue siendo posible ----------------------------

    def test_collecting_from_the_record_menu_needs_no_selection(self):
        """Un adelanto no tiene deuda que marcar: es lo que lo hace adelanto.

        El menú de la ficha no manda `origen`, así que no pasa por la guarda.
        """
        response = self.client.get(
            reverse("payments:register", args=[self.customer.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_charges"], [])

    def test_the_board_tells_the_browser_which_buttons_need_a_row(self):
        response = self.client.get(self.board_url())

        self.assertContains(response, 'data-exige-seleccion="cobrar"')
        self.assertContains(response, 'data-exige-seleccion="aplazar"')
        self.assertContains(response, 'name="origen"')


class DebtBoardPageSizeTests(PaymentsTestCase):
    """El selector de filas del tablero."""

    def setUp(self):
        super().setUp()

        self.user = self.make_user("consulta1", permissions=["view_charge"])

        for offset in range(3):
            Charge.objects.create(
                customer=self.customer,
                concept=Charge.Concept.OTHER,
                description="Cargo %s" % offset,
                amount=Decimal("10.00"),
                due_date=timezone.localdate() + timedelta(days=offset),
            )

    def url(self):
        return reverse("payments:debt", args=[self.customer.pk])

    def test_it_defaults_to_fifteen_rows(self):
        self.login(self.user)

        response = self.client.get(self.url())

        self.assertEqual(response.context["page_size"], 15)
        self.assertEqual(len(response.context["page_obj"].object_list), 3)

    def test_a_bigger_size_shows_more_rows_per_page(self):
        """Los tamaños grandes siguen ahí, y no por comodidad.

        «Cobrar» y «Compromiso» actúan sobre las filas marcadas, y la marca no
        cruza de página: saldar una mora larga de una vez exige poder verla
        entera.
        """
        self.login(self.user)

        response = self.client.get(self.url(), {"filas": "500"})

        self.assertEqual(response.context["page_size"], 500)
        self.assertFalse(response.context["is_paginated"])

    def test_the_summary_counts_the_whole_debt_not_the_page(self):
        """El resumen del encabezado no depende del tamaño de página.

        Si leyera de la tabla recortada diría «20 deudas abiertas» cuando el
        abonado tiene 30, y el operador cerraría la atención creyendo que la
        cuenta está más limpia de lo que está.
        """
        self.login(self.user)

        response = self.client.get(self.url(), {"filas": "20"})

        self.assertEqual(response.context["debt"]["count"], 3)

    def test_an_unsupported_size_falls_back_to_the_default(self):
        """Un valor cualquiera en la URL no debe romper la pantalla."""
        self.login(self.user)

        for value in ("7", "abc", "-1", ""):
            with self.subTest(value=value):
                response = self.client.get(self.url(), {"filas": value})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_size"], 15)
