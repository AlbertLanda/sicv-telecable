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

from apps.payments.models import Charge, ChargeConcept, Payment, ZERO
from apps.payments.services import (
    create_manual_charge,
    daily_rate,
    prorated_amount,
    register_payment,
)
from apps.payments.tests.base import PaymentsTestCase


def concept(code):
    """El concepto del catálogo con ese código.

    Los siembra la migración, así que están en toda base de pruebas. Se
    busca por código y no por nombre porque el nombre lleva tildes y se
    puede corregir desde el admin.
    """
    return ChargeConcept.objects.get(code=code)


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

    def test_the_screen_offers_the_whole_catalogue(self):
        """El desplegable es el catálogo de la empresa, no cuatro familias.

        Doscientos y pico conceptos -planes, publicidad, alquileres, ajustes-
        que la empresa mantiene desde el admin. Lo que el código conserva es
        la familia de cada uno, que es lo que decide cómo se comporta la deuda.
        """
        self.login(self.issuer)
        response = self.client.get(self.url())
        ofrecidos = response.context["form"].fields["concept"].queryset

        self.assertIn(concept("mensualidad"), ofrecidos)
        self.assertIn(concept("reconexion"), ofrecidos)
        self.assertIn(concept("internet-100mg"), ofrecidos)
        self.assertIn(concept("materiales"), ofrecidos)
        self.assertGreater(ofrecidos.count(), 200)

    def test_a_concept_that_is_no_longer_sold_leaves_the_list(self):
        """Se retira del desplegable, pero no se borra.

        Las deudas que ya lo llevan tienen que poder seguir diciendo qué se
        cobró, así que el catálogo se da de baja, no se elimina.
        """
        self.login(self.issuer)
        retirado = concept("iptv-oro")
        retirado.is_active = False
        retirado.save()

        response = self.client.get(self.url())

        self.assertNotIn(
            retirado, response.context["form"].fields["concept"].queryset
        )

    def test_the_family_travels_with_each_option(self):
        """El navegador tiene que saber cuáles se reparten en días.

        Con el catálogo en la base ya no basta con mirar el valor de la
        opción: cuál se comporta como mensualidad lo dice su familia.
        """
        self.login(self.issuer)
        html = self.client.get(self.url()).content.decode()

        # `assertInHTML` y no una comparacion de texto: el orden de los
        # atributos que pinta Django no es parte del contrato.
        self.assertInHTML(
            '<option value="%s" data-family="MONTHLY" selected>MENSUALIDAD</option>'
            % concept("mensualidad").pk,
            html,
            count=1,
        )
        self.assertInHTML(
            '<option value="%s" data-family="OTHER">MATERIALES</option>'
            % concept("materiales").pk,
            html,
            count=1,
        )

    def test_the_charge_keeps_the_concept_that_was_charged(self):
        """La familia dice cómo se comporta; el concepto, qué se cobró.

        Sin el segundo, una deuda de «INTERNET 300MG» y una de «ALQUILER
        TERRENO» serían la misma cosa en la base: dos mensualidades.
        """
        self.login(self.issuer)
        elegido = concept("internet-300mg")

        self.client.post(
            self.url(),
            {
                "concept": elegido.pk,
                "description": "",
                "amount": "120.00",
                "due_date": (self.today + timedelta(days=10)).isoformat(),
            },
        )

        charge = Charge.objects.get()

        self.assertEqual(charge.concept_item, elegido)
        self.assertEqual(charge.concept, Charge.Concept.MONTHLY)
        self.assertEqual(charge.description, "INTERNET 300MG")

    def test_a_manual_charge_is_issued_and_appears_in_the_debt(self):
        self.login(self.issuer)

        response = self.client.post(
            self.url(),
            {
                "concept": concept("reconexion").pk,
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

    def test_the_charge_is_issued_against_the_customer_alone(self):
        """La suscripción salió de la pantalla.

        Se emitía contra el abonado incluso cuando el desplegable existía -su
        opción vacía era la de siempre-, y ofrecerlo abría la puerta a colgarle
        un cargo del servicio de otra persona si alguien enviaba un id ajeno.
        """
        self.login(self.issuer)

        response = self.client.get(self.url())

        self.assertNotIn("subscription", response.context["form"].fields)

        self.client.post(
            self.url(),
            {
                "concept": concept("reconexion").pk,
                "description": "Reconexión por corte",
                "amount": "20.00",
                "due_date": (self.today + timedelta(days=10)).isoformat(),
                "early_discount": "",
                "discount_deadline": "",
                "subscription": "99",
            },
        )

        self.assertIsNone(Charge.objects.get().subscription)

    def test_an_invalid_amount_does_not_create_anything(self):
        self.login(self.issuer)

        response = self.client.post(
            self.url(),
            {
                "concept": concept("otros").pk,
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


class TheEarlyPaymentDiscountIsNotIssuedByHandTests(PaymentsTestCase):
    """El pronto pago salió de la pantalla de nueva deuda.

    Lo concede el ciclo mensual desde la política de cobro del plan, que es
    donde vive la regla: cuánto se descuenta y hasta cuándo. Concederlo a mano
    en cada emisión abría la puerta a que dos ventanillas dieran plazos
    distintos por el mismo concepto.

    El servicio y el modelo lo siguen aceptando -es por donde entra el del
    ciclo-, así que lo que se fija aquí es que la ventanilla no lo emita.
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
            "concept": concept("reconexion").pk,
            "description": "Reconexión por corte",
            "amount": "20.00",
            "due_date": (self.today + timedelta(days=10)).isoformat(),
        }
        data.update(overrides)

        return data

    def test_the_screen_no_longer_asks_for_it(self):
        response = self.client.get(self.url())
        form = response.context["form"]
        body = response.content.decode()

        self.assertNotIn("early_discount", form.fields)
        self.assertNotIn("discount_deadline", form.fields)
        self.assertNotIn('name="early_discount"', body)
        self.assertNotIn("Pronto pago", body)

    def test_a_discount_sent_anyway_does_not_reach_the_charge(self):
        """El campo no está, pero el POST se escribe a mano igual de fácil."""
        self.client.post(
            self.url(),
            self.payload(
                early_discount="5.00",
                discount_deadline=(self.today + timedelta(days=3)).isoformat(),
            ),
        )

        charge = Charge.objects.get()

        self.assertEqual(charge.early_discount, ZERO)
        self.assertIsNone(charge.discount_deadline)

    def test_the_charge_is_issued_as_always(self):
        self.client.post(self.url(), self.payload())

        charge = Charge.objects.get()

        self.assertEqual(charge.amount, Decimal("20.00"))
        self.assertEqual(charge.early_discount, ZERO)

    def test_the_monthly_cycle_still_grants_it(self):
        """Lo que sale es la emisión a mano, no el descuento.

        El ciclo lo sigue concediendo desde la política del plan, que es de
        donde tiene que salir.
        """
        charge = create_manual_charge(
            customer=self.customer,
            concept=Charge.Concept.MONTHLY,
            description="Mensualidad",
            amount=Decimal("80.00"),
            due_date=self.today + timedelta(days=10),
            early_discount=Decimal("5.00"),
            discount_deadline=self.today + timedelta(days=3),
        )

        self.assertEqual(charge.early_discount, Decimal("5.00"))


class TheScreenOpensReadyForTheUsualCaseTests(PaymentsTestCase):
    """Con qué llega escrita la pantalla al abrirse.

    La deuda que se emite a diario es la mensualidad del abonado por el monto
    de su plan. Abrir en el primer concepto de la lista y con el monto en
    blanco obligaba a corregir dos campos en cada emisión, y el monto había
    que ir a buscarlo a la ficha del servicio.
    """

    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()
        self.issuer = self.make_user(
            "emisor1", permissions=["view_charge", "add_charge"]
        )
        self.login(self.issuer)

    def form(self):
        response = self.client.get(
            reverse("payments:charge_create", args=[self.customer.pk])
        )

        return response.context["form"]

    def body(self):
        response = self.client.get(
            reverse("payments:charge_create", args=[self.customer.pk])
        )

        return response.content.decode()

    def test_the_concept_opens_on_the_monthly_fee(self):
        self.assertEqual(
            self.form()["concept"].value(), concept("mensualidad").pk
        )

    def test_the_amount_arrives_written_with_the_plan_price(self):
        self.assertEqual(
            Decimal(self.form()["amount"].value()),
            self.subscription.total_monthly_price,
        )

    def test_the_amount_can_still_be_edited(self):
        """Llega escrito, no bloqueado: un acuerdo se escribe encima."""
        self.assertNotIn("readonly", str(self.form()["amount"]))
        self.assertFalse(self.form().fields["amount"].disabled)

    def test_pay_until_opens_on_today(self):
        self.assertEqual(self.form()["due_date"].value(), self.today)

    def test_the_subscription_is_no_longer_asked_for(self):
        """Salió de la pantalla: la deuda se emite contra el abonado."""
        self.assertNotIn("subscription", self.form().fields)
        self.assertNotIn('name="subscription"', self.body())

    def test_the_concept_does_not_offer_an_empty_option(self):
        """«---------» no era una respuesta posible: el concepto es obligatorio.

        Lo unico que hacia era dar una pantalla que parece sin llenar, y dejar
        que el navegador se quedara en esa opcion al restaurar el formulario
        tras una recarga, por encima del valor inicial.
        """
        ofrecidos = [value for value, _ in self.form().fields["concept"].choices]

        self.assertNotIn("", ofrecidos)
        self.assertNotIn("---------", str(self.form()["concept"]))

    def test_the_quantity_is_shown_as_a_whole_one(self):
        """Un 1 pelado: los cinco decimales no dicen nada en un campo fijo."""
        self.assertIn('value="1"', str(self.form()["quantity"]))

    def test_the_description_carries_no_placeholder(self):
        self.assertNotIn("placeholder", str(self.form()["description"]))

    def test_the_date_reaches_the_browser_in_the_format_it_understands(self):
        """Un <input type="date"> solo entiende aaaa-mm-dd.

        Con el idioma en español Django pinta 09/09/2026, que el navegador
        descarta dejando el campo vacío: la fecha inicial no llegaba, y una
        que volviera con errores de validación se perdía por el camino.
        """
        self.assertIn(
            'value="%s"' % self.today.isoformat(),
            str(self.form()["due_date"]),
        )

    def test_a_customer_without_an_active_subscription_opens_blank(self):
        """Sin plan del que copiar, el monto queda vacío y no en cero.

        Un cero escrito parece un monto puesto a propósito y el formulario lo
        rechaza igual; en blanco se lee como lo que es, un campo por llenar.
        """
        from apps.services.models import Subscription

        Subscription.objects.filter(customer=self.customer).update(
            status=Subscription.Status.SUSPENDED
        )

        self.assertIsNone(self.form()["amount"].value())


class TheDailyProrationTests(PaymentsTestCase):
    """El prorrateo del mes en días.

    Sirve para el periodo partido: un alta a mitad de mes o una reconexión
    que no cubre el mes entero. El operador sabe cuántos días cobra, no cuánto
    suman, y hasta ahora los calculaba aparte.
    """

    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()
        self.issuer = self.make_user(
            "emisor1", permissions=["view_charge", "add_charge"]
        )
        self.login(self.issuer)

    def screen(self):
        return self.client.get(
            reverse("payments:charge_create", args=[self.customer.pk])
        )

    def test_the_day_is_the_monthly_fee_over_a_thirty_day_month(self):
        """Mes comercial: el mismo corte de cinco días vale igual en febrero.

        Con los días reales del calendario, el prorrateo de febrero saldría
        más caro que el de marzo por el mismo servicio.
        """
        self.assertEqual(daily_rate(Decimal("60.00")), Decimal("2.00"))
        self.assertEqual(daily_rate(Decimal("45.00")), Decimal("1.50"))

    def test_a_customer_without_a_monthly_fee_has_no_day_to_split(self):
        self.assertEqual(daily_rate(Decimal("0.00")), Decimal("0.00"))
        self.assertEqual(daily_rate(None), Decimal("0.00"))

    def test_the_amount_multiplies_the_day_the_operator_is_shown(self):
        """Diez días de S/ 1.50 son quince exactos.

        Se multiplica el día ya redondeado y no la mensualidad en crudo:
        45/30 da 1.50 justo, pero 50/30 da 1.6666..., y el operador que lee
        «S/ 1.67 por día» espera que diez días sean S/ 16.70.
        """
        self.assertEqual(
            prorated_amount(Decimal("45.00"), 10), Decimal("15.00")
        )
        self.assertEqual(
            prorated_amount(Decimal("50.00"), 10), Decimal("16.70")
        )

    def test_a_full_month_of_days_is_the_monthly_fee(self):
        """El mes entero vale el plan, no la suma de sus treinta días.

        Con S/ 79.00 el día redondeado es 2.63, y treinta de esos dan 78.90:
        diez céntimos por debajo de lo contratado. El redondeo puede repartir
        un periodo partido, no rebajar el plan.
        """
        self.assertEqual(
            prorated_amount(Decimal("45.00"), 30), Decimal("45.00")
        )
        self.assertEqual(
            prorated_amount(Decimal("79.00"), 30), Decimal("79.00")
        )

    def test_a_period_that_is_not_the_whole_month_follows_the_day(self):
        """Diez días de S/ 2.63 son 26.30, lo que suma la pantalla."""
        self.assertEqual(daily_rate(Decimal("79.00")), Decimal("2.63"))
        self.assertEqual(
            prorated_amount(Decimal("79.00"), 10), Decimal("26.30")
        )

    def test_no_days_are_not_a_debt(self):
        self.assertEqual(prorated_amount(Decimal("45.00"), 0), Decimal("0.00"))
        self.assertEqual(prorated_amount(Decimal("45.00"), -3), Decimal("0.00"))

    def test_the_screen_carries_the_day_already_calculated(self):
        """El valor del día lo divide el servidor, no el navegador.

        Si lo dividiera cada lado por su cuenta, la cifra que el operador lee
        y la que guarda el servidor podrían no coincidir en el céntimo.
        """
        context = self.screen().context

        self.assertEqual(
            context["daily_rate"],
            daily_rate(self.subscription.total_monthly_price),
        )

    def test_the_numbers_reach_the_script_with_a_decimal_point(self):
        """Con el idioma en español, «2.63» se pinta «2,63».

        `parseFloat("2,63")` corta en la coma y devuelve 2: el valor del día
        llegaba al script hecho un entero y el prorrateo cobraba de menos.
        """
        html = self.screen().content.decode()
        esperado = daily_rate(self.subscription.total_monthly_price)

        self.assertIn('data-daily="%s"' % esperado, html)
        self.assertNotIn(str(esperado).replace(".", ","), html)

    def test_the_button_is_offered_on_the_monthly_fee(self):
        """Y llega ya visible: no aparece un instante después de abrir."""
        self.assertTrue(self.screen().context["es_mensualidad"])

    def test_the_button_is_not_offered_on_another_concept(self):
        """Una reconexión cuesta lo que cuesta, no medio mes."""
        response = self.client.post(
            reverse("payments:charge_create", args=[self.customer.pk]),
            {
                "concept": concept("reconexion").pk,
                "description": "Reconexión",
                "amount": "0",
                "due_date": self.today.isoformat(),
                "early_discount": "",
                "discount_deadline": "",
            },
        )

        self.assertFalse(response.context["es_mensualidad"])


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
            "concept": concept("reconexion").pk,
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

    def test_the_quantity_stays_at_one_however_it_is_sent(self):
        """La cantidad está bloqueada: se emite de a una.

        No basta con deshabilitar el campo en el HTML -eso se reescribe desde
        el navegador-: el formulario lo declara `disabled`, así que Django
        descarta lo que venga en el POST y toma el valor inicial. Antes un
        negativo llegaba a validarse; ahora ni se lee.
        """
        self.login(self.issuer)

        self.client.post(
            reverse("payments:charge_create", args=[self.customer.pk]),
            self.payload(quantity="-2"),
        )

        self.assertEqual(Charge.objects.get().quantity, Decimal("1.00000"))

    def test_a_negative_discount_cannot_be_slipped_in(self):
        """Un descuento en negativo subiría lo que el abonado debe.

        La pantalla ya no pide el pronto pago, así que no hay dónde escribirlo
        mal; lo que se fija es que enviarlo por el POST tampoco lo cuele.
        """
        self.login(self.issuer)

        self.client.post(
            reverse("payments:charge_create", args=[self.customer.pk]),
            self.payload(early_discount="-5.00"),
        )

        self.assertEqual(Charge.objects.get().early_discount, ZERO)

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
