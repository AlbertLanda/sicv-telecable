"""
Talonarios de comprobantes y lugar de cobro.

Dos cosas que el sistema anterior resolvía en la misma pantalla y que aquí
tenían que entrar juntas:

1. De qué block sale el comprobante. La serie ya no es un texto: es un
   talonario con su propio correlativo, y hay tres que se imprimen «S010»
   sin ser el mismo block.
2. Dónde entró el dinero. La sede dice de qué ciudad es la caja; la oficina
   dice cuál de sus ventanillas, y el depósito de la sede recoge lo que
   llegó por banco sin pasar por ninguna.
"""

import re
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.organization.context_processors import (
    ACTIVE_BRANCH_SESSION_KEY,
    ACTIVE_OFFICE_SESSION_KEY,
)
from apps.organization.models import Office
from apps.payments.forms import PaymentRegisterForm
from apps.payments.models import Charge, Payment, Receipt, ReceiptSequence
from apps.payments.services import receipt_series_options, register_payment
from apps.payments.tests.base import PaymentsTestCase


class TalonarioTests(PaymentsTestCase):
    """El correlativo pertenece al block, no a la serie que se imprime."""

    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo de prueba",
            amount=Decimal("50.00"),
            due_date=timezone.localdate() + timedelta(days=10),
        )

    def cobrar(self, **kwargs):
        opciones = {
            "customer": self.customer,
            "amount": Decimal("10.00"),
            "method": Payment.Method.CASH,
            "branch": self.branch,
            "user": self.cashier,
        }
        opciones.update(kwargs)

        return register_payment(**opciones)

    def test_the_seeded_books_start_where_the_old_system_left_them(self):
        """El número anotado es el próximo a imprimir, no el último entregado.

        Guardarlo tal cual como «último emitido» saltaría el 0041316: el
        primer recibo de B001 saldría 0041317 y el talonario de papel y el
        sistema dejarían de coincidir desde el primer cobro.
        """
        esperados = {
            "B001": 41316,
            "B002": 31985,
            "F001": 8323,
            "F002": 5599,
            "S010-VELOCIDAD": 3031,
            "S010-RED-OPTICA": 267,
            "S010-SPEEDY": 569,
            "VCOND": 30821,
        }

        for code, proximo in esperados.items():
            with self.subTest(code=code):
                sequence = ReceiptSequence.objects.get(code=code)

                self.assertEqual(sequence.next_number, proximo)

    def test_the_first_receipt_of_a_book_carries_the_number_announced(self):
        _, receipt = self.cobrar(series="B001")

        self.assertEqual(receipt.number, 41316)
        self.assertEqual(receipt.series, "B001")
        self.assertEqual(receipt.full_number, "B001-0041316")

    def test_the_next_one_continues(self):
        self.cobrar(series="B001")
        _, receipt = self.cobrar(series="B001")

        self.assertEqual(receipt.number, 41317)

    def test_the_three_s010_books_run_on_their_own(self):
        """«S010» nombra tres blocks distintos y cada uno va por su cuenta.

        Amarrar el correlativo a la serie impresa haría que el segundo block
        continuara la cuenta del primero, y el papel diría otra cosa.
        """
        _, velocidad = self.cobrar(series="S010-VELOCIDAD")
        _, red = self.cobrar(series="S010-RED-OPTICA")
        _, speedy = self.cobrar(series="S010-SPEEDY")

        self.assertEqual(velocidad.number, 3031)
        self.assertEqual(red.number, 267)
        self.assertEqual(speedy.number, 569)

        for receipt in (velocidad, red, speedy):
            self.assertEqual(receipt.series, "S010")

    def test_two_books_may_print_the_same_series_and_number(self):
        """Lo acepta el modelo porque así es el papel que ya está impreso.

        Lo que no puede repetirse es el número dentro de un mismo block, que
        es lo que fija la restricción de base de datos.
        """
        _, red = self.cobrar(series="S010-RED-OPTICA", number=900)
        _, speedy = self.cobrar(series="S010-SPEEDY", number=900)

        self.assertEqual(red.full_number, speedy.full_number)
        self.assertNotEqual(red.sequence_id, speedy.sequence_id)

    def test_a_book_never_repeats_a_number(self):
        self.cobrar(series="B001", number=500)

        with self.assertRaises(ValidationError):
            self.cobrar(series="B001", number=500)

    def test_a_written_number_wins_over_the_proposed_one(self):
        """El campo es editable porque hay blocks de papel ya numerados."""
        _, receipt = self.cobrar(series="B001", number=99000)

        self.assertEqual(receipt.number, 99000)

    def test_writing_a_number_ahead_moves_the_book_forward(self):
        """Saltar del 41316 al 99000 no deja el correlativo detrás.

        Si se quedara donde estaba, el siguiente cobro propondría 41317 y
        recorrería otra vez números que ya se entregaron.
        """
        self.cobrar(series="B001", number=99000)

        _, siguiente = self.cobrar(series="B001")

        self.assertEqual(siguiente.number, 99001)

    def test_a_hand_numbered_book_refuses_to_guess(self):
        """Los blocks de un cobrador vienen numerados de papel.

        Proponerles un número sería inventarlo: el que toca lo sabe quien
        tiene el block en la mano.
        """
        sequence = ReceiptSequence.objects.get(code="JU1")

        self.assertIsNone(sequence.next_number)

        with self.assertRaises(ValidationError):
            self.cobrar(series="JU1")

    def test_a_hand_numbered_book_accepts_the_number_written(self):
        _, receipt = self.cobrar(series="JU1", number=77)

        self.assertEqual(receipt.number, 77)
        self.assertEqual(receipt.series, "JU1")

    def test_the_receipt_remembers_which_book_it_came_from(self):
        _, receipt = self.cobrar(series="F002")

        self.assertEqual(receipt.sequence.code, "F002")
        self.assertEqual(receipt.sequence.label, "F:F002 - INVERSIONES")


class LugarDeCobroTests(PaymentsTestCase):
    """Dónde entró el dinero, que no siempre es donde está el operador."""

    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo de prueba",
            amount=Decimal("50.00"),
            due_date=timezone.localdate() + timedelta(days=10),
        )

        self.ventanilla = Office.objects.create(
            branch=self.branch,
            code="SED01-CAJA",
            name="Caja 1",
        )

        self.deposito = Office.objects.create(
            branch=self.branch,
            code="SED01-DEPOSITO",
            name="Deposito",
            is_deposit=True,
        )

        self.user = self.make_user(
            "cajero",
            permissions=["view_charge", "add_payment", "view_payment", "view_receipt"],
        )
        self.login(self.user)

    def url(self):
        return reverse("payments:register", args=[self.customer.pk])

    def datos(self, **extra):
        datos = {
            "amount": "50.00",
            "method": Payment.Method.CASH,
            "settled": "1",
            "series": "B001",
        }
        datos.update(extra)

        return datos

    def test_the_payment_records_the_office_chosen_in_the_top_bar(self):
        """La barra dice desde dónde se atiende; el cobro lo hereda.

        Sin esto la cobranza solo podría decir la ciudad, y el arqueo de una
        sede con cinco ventanillas no sabría de cuál salió el dinero.
        """
        session = self.client.session
        session[ACTIVE_OFFICE_SESSION_KEY] = self.ventanilla.pk
        session.save()

        self.client.post(self.url(), self.datos())

        payment = Payment.objects.latest("pk")

        self.assertEqual(payment.office, self.ventanilla)

    def test_the_deposit_chosen_in_the_top_bar_is_where_the_money_lands(self):
        """Lo que llega por banco no lo recibe nadie en mostrador.

        El depósito de la sede se elige arriba, como cualquier otra
        ubicación, y el cobro lo hereda igual que heredaría una ventanilla.
        """
        session = self.client.session
        session[ACTIVE_OFFICE_SESSION_KEY] = self.deposito.pk
        session.save()

        self.client.post(
            self.url(),
            self.datos(method=Payment.Method.TRANSFER, reference="OP-9911"),
        )

        payment = Payment.objects.latest("pk")

        self.assertEqual(payment.office, self.deposito)

    def test_the_screen_shows_the_place_without_asking_for_it(self):
        """Un solo sitio donde se decide dónde se cobra.

        Preguntarlo también aquí eran dos sitios para lo mismo, y el que se
        quedaba sin mirar -el de la barra- seguía gobernando la sesión.
        """
        session = self.client.session
        session[ACTIVE_OFFICE_SESSION_KEY] = self.ventanilla.pk
        session.save()

        response = self.client.get(self.url())
        body = response.content.decode()

        # `name="office"` aparece igual en la pagina: es el formulario del
        # selector de la barra. Lo que no debe haber es un desplegable donde
        # se vuelva a elegir.
        self.assertNotIn('<select name="office"', body)
        self.assertNotIn("office", response.context["form"].fields)
        self.assertIn(str(self.ventanilla), body)

    def test_without_offices_the_collection_still_goes_through(self):
        """Un despliegue sin padrón de oficinas no se queda sin cobrar.

        La sede basta para saber qué caja lo recibió; exigir la oficina
        dejaría la ventanilla parada por un padrón que nadie llenó.
        """
        Office.objects.all().delete()

        response = self.client.post(self.url(), self.datos())
        payment = Payment.objects.latest("pk")

        self.assertEqual(response.status_code, 302)
        self.assertIsNone(payment.office)


class FormularioDeCobroTests(PaymentsTestCase):
    """Lo que la pantalla ofrece antes de que el operador toque nada."""

    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo de prueba",
            amount=Decimal("50.00"),
            due_date=timezone.localdate() + timedelta(days=10),
        )

        self.user = self.make_user(
            "cajero2",
            permissions=["view_charge", "add_payment", "view_payment", "view_receipt"],
        )
        self.login(self.user)

    def pantalla(self):
        return self.client.get(reverse("payments:register", args=[self.customer.pk]))

    def test_the_dropdown_lists_the_books_of_the_old_system(self):
        body = self.pantalla().content.decode()

        for label in (
            "B: JU1 - JUAN URBAJO",
            "B:B001 - CABLE LOS ANDES",
            "S:S010 - RED OPTICA",
            "V.COND - CABLE LOS ANDES",
        ):
            with self.subTest(label=label):
                self.assertIn(label, body)

    def test_each_option_carries_the_number_that_would_be_printed(self):
        """La correspondencia serie/número es un dato del talonario.

        Viaja en la propia opción para que elegir la serie complete el número
        sin volver a preguntarle al servidor en cada cambio.
        """
        body = self.pantalla().content.decode()

        # Con sus ceros: la opcion propone lo que se va a escribir en el
        # campo, y el campo muestra el numero tal como ira impreso.
        self.assertIn('data-numero="0041316"', body)
        self.assertIn('data-numero="0000267"', body)

    def test_a_hand_numbered_book_proposes_nothing(self):
        body = self.pantalla().content.decode()
        sequence = ReceiptSequence.objects.get(code="JU1")

        self.assertIsNone(sequence.next_number)
        self.assertIn('data-numero=""', body)

    def test_the_number_arrives_proposed_and_editable(self):
        """Dejó de ser un campo bloqueado: hay blocks que ya vienen numerados.

        Llega escrito igual, porque el caso normal es aceptar el que propone
        el talonario y hacerlo teclear cada vez sería trabajo inventado.
        """
        response = self.pantalla()
        body = response.content.decode()
        campo = response.context["form"]["number"]

        self.assertIn('name="number"', body)
        self.assertNotIn("disabled", str(campo))
        self.assertEqual(campo.value(), "0041316")

    def test_the_proposed_number_keeps_its_leading_zeros(self):
        """El campo muestra lo que se va a imprimir, no el entero pelado.

        El comprobante que se entrega dice «B001-0041316». Sin los ceros el
        operador leía 41316 en pantalla y otra cosa en el papel, y el que
        después buscaba ese papel no encontraba por cuál de los dos buscar.
        """
        response = self.pantalla()

        self.assertEqual(response.context["form"]["number"].value(), "0041316")
        self.assertIn('value="0041316"', response.content.decode())

    def test_a_number_written_with_zeros_is_the_same_number(self):
        """«003031» y «3031» son el mismo comprobante.

        Los ceros son cómo se lee, no cuánto vale: exigirlos -o prohibirlos-
        sería inventarle al operador una regla que el block de papel no tiene.
        """
        formulario = PaymentRegisterForm(
            data={
                "amount": "50.00",
                "method": Payment.Method.CASH,
                "settled": "1",
                "series": "B001",
                "number": "003031",
            }
        )

        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(formulario.cleaned_data["number"], 3031)

    def test_a_number_that_is_not_digits_is_rejected(self):
        formulario = PaymentRegisterForm(
            data={
                "amount": "50.00",
                "method": Payment.Method.CASH,
                "settled": "1",
                "series": "B001",
                "number": "30-31",
            }
        )

        self.assertFalse(formulario.is_valid())
        self.assertIn("number", formulario.errors)

    def test_the_receipt_is_issued_with_the_number_written_with_zeros(self):
        """De punta a punta: lo escrito con ceros llega al papel igual."""
        self.client.post(
            reverse("payments:register", args=[self.customer.pk]),
            {
                "amount": "50.00",
                "method": Payment.Method.CASH,
                "settled": "1",
                "series": "B001",
                "number": "0041316",
            },
        )
        receipt = Receipt.objects.latest("pk")

        self.assertEqual(receipt.number, 41316)
        self.assertEqual(receipt.full_number, "B001-0041316")

    def test_the_screen_opens_on_the_first_book_that_numbers_itself(self):
        """No en el primero de la lista, que es un block de cobrador.

        Esos vienen numerados de papel y proponen vacío, así que abrir ahí
        dejaría el número en blanco y un «Aceptar» sin tocar nada devolvería
        un error por algo que el operador no eligió.
        """
        response = self.pantalla()

        self.assertEqual(response.context["form"]["series"].value(), "B001")

    def test_the_systems_own_book_is_not_on_the_list(self):
        body = self.pantalla().content.decode()

        self.assertNotIn('value="R001"', body)

    def test_the_debt_table_shows_the_columns_of_the_window(self):
        """Las columnas del sistema anterior, en su orden.

        «Plan» y «Mes» iban antes en una sola celda -el plan con el periodo
        debajo-, y el operador que compara con el papel tenía que leer dos
        datos donde el papel tiene dos columnas.
        """
        body = self.pantalla().content.decode()
        cabecera = body.split("<thead>")[1].split("</thead>")[0]
        columnas = re.findall(r"<th[^>]*>(.*?)</th>", cabecera, re.S)
        columnas = [texto.strip() for texto in columnas]

        self.assertEqual(
            columnas,
            [
                "Cantidad", "Abonado", "Plan", "Mes",
                "Moneda", "Monto", "Desc", "Total",
            ],
        )

    def test_the_settled_choice_no_longer_carries_a_hint(self):
        """La ayuda salió: las dos opciones se llaman «Sí» y «No (Pendiente)»."""
        body = self.pantalla().content.decode()

        self.assertNotIn("la deuda no baja hasta confirmarlo", body)


class ComprobanteDelTalonarioTests(PaymentsTestCase):
    """El número que se guarda es el que se entrega."""

    def test_the_receipt_number_is_padded_to_six_digits(self):
        charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo de prueba",
            amount=Decimal("50.00"),
            due_date=timezone.localdate() + timedelta(days=10),
        )

        _, receipt = register_payment(
            customer=self.customer,
            amount=Decimal("50.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            series="S010-RED-OPTICA",
            allocations=[(charge, Decimal("50.00"))],
        )

        self.assertEqual(receipt.full_number, "S010-0000267")
        self.assertEqual(Receipt.objects.filter(sequence__code="S010-RED-OPTICA").count(), 1)


class PadronDeTalonariosPorOficinaTests(PaymentsTestCase):
    """Cada ventanilla ofrece los blocks que tiene en el cajón.

    Un talonario es papel, y el papel está en un sitio. Ofrecer en Apata un
    block que vive en Oroya invita a numerar algo que nadie tiene delante, y
    el número que salga no va a coincidir con ningún talonario real.

    El padrón entra por migración, así que estas pruebas leen el que el
    sistema trae de fábrica en vez de sembrar uno propio: lo que se está
    comprobando es que las diez listas del sistema anterior quedaron escritas
    tal cual.
    """

    def setUp(self):
        super().setUp()

        self.charge = Charge.objects.create(
            customer=self.customer,
            concept=Charge.Concept.OTHER,
            description="Cargo de prueba",
            amount=Decimal("50.00"),
            due_date=timezone.localdate() + timedelta(days=10),
        )

        self.user = self.make_user(
            "cajera",
            permissions=["view_charge", "add_payment", "view_payment"],
        )
        self.login(self.user)

    def office(self, code):
        return Office.objects.get(code=code)

    def books_of(self, code):
        """Los códigos que esa ventanilla ofrece, en su orden, sin los de mano."""
        return [
            sequence.code
            for sequence in receipt_series_options(office=self.office(code))
            if sequence.autonumber
        ]

    def atender_desde(self, code):
        """Pone la barra superior en esa ventanilla, como haría el operador."""
        office = self.office(code)

        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = office.branch.pk
        session[ACTIVE_OFFICE_SESSION_KEY] = office.pk
        session.save()

        return office

    def test_each_office_offers_the_books_of_the_old_system(self):
        """Las listas son las del sistema que se reemplaza, oficina por oficina."""
        esperado = {
            "JAUJA-PRINCIPAL": [
                "B001", "B002", "F001", "F002",
                "S010-VELOCIDAD", "S010-RED-OPTICA", "S010-SPEEDY", "VCOND",
            ],
            "JAUJA-CAJAS": [
                "B003-CLA", "F002-CLA",
                "S003-SPEEDY", "S003-VELOCIDAD", "S003-RED-OPTICA", "VCOND",
            ],
            "JAUJA-YAUYOS": ["VCOND"],
            "OROYA-OF2": ["B001-INV", "B002-CLA", "F001-INV", "VCOND-INV"],
        }

        for code, codigos in esperado.items():
            with self.subTest(oficina=code):
                self.assertEqual(self.books_of(code), codigos)

    def test_each_office_keeps_its_own_order(self):
        """Los mismos tres blocks, apilados distinto en cada ventanilla.

        «S003» sale en Jauja Cajas como SPEEDY, VELOCIDAD, RED ÓPTICA y en
        Huancayo El Tambo como VELOCIDAD, RED ÓPTICA, SPEEDY. Son los mismos
        tres talonarios: por eso el orden vive en la relación y no en el
        talonario, donde solo cabría una de las dos respuestas.
        """
        cajas = [code for code in self.books_of("JAUJA-CAJAS") if code.startswith("S003")]
        tambo = [code for code in self.books_of("HUANCAYO-ELTAMBO") if code.startswith("S003")]

        self.assertEqual(cajas, ["S003-SPEEDY", "S003-VELOCIDAD", "S003-RED-OPTICA"])
        self.assertEqual(tambo, ["S003-VELOCIDAD", "S003-RED-OPTICA", "S003-SPEEDY"])

    def test_a_shared_book_keeps_a_single_counter(self):
        """«F001 - CABLE LOS ANDES» es un block, no uno por oficina.

        Está en el cajón del Local Principal de Jauja, en el de la Oficina 2 y
        en el de Apata, y va por el 8323 en los tres. Si cada ventanilla
        llevara su propia cuenta, tres cajas emitirían el mismo número sobre
        el mismo papel.
        """
        self.assertIn("F001", self.books_of("JAUJA-PRINCIPAL"))
        self.assertIn("F001", self.books_of("JAUJA-APATA"))

        _, primero = register_payment(
            customer=self.customer,
            amount=Decimal("10.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            series="F001",
        )
        _, segundo = register_payment(
            customer=self.customer,
            amount=Decimal("10.00"),
            method=Payment.Method.CASH,
            branch=self.branch,
            user=self.cashier,
            series="F001",
        )

        self.assertEqual(primero.number, 8323)
        self.assertEqual(segundo.number, 8324)

    def test_the_collector_books_are_offered_everywhere(self):
        """Los blocks de un cobrador no son de una ventanilla.

        Son papel que él lleva encima, así que aparecen se cobre donde se
        cobre. Por eso no figuran en la lista de ninguna oficina y aquí se
        comprueba que están en todas.
        """
        for office in Office.objects.all():
            with self.subTest(oficina=office.code):
                codigos = [
                    sequence.code
                    for sequence in receipt_series_options(office=office)
                ]

                self.assertIn("JU1", codigos)

    def test_the_deposit_offers_what_its_main_office_offers(self):
        """Lo que llega por banco cae en el depósito, y tiene que poder emitir.

        No tiene blocks propios -nadie está parado ahí-, así que ofrece los
        del local principal de su sede. Sin talonario no se podría registrar
        una transferencia.
        """
        self.assertEqual(
            self.books_of("JAUJA-DEPOSITO"),
            self.books_of("JAUJA-PRINCIPAL"),
        )

    def test_without_an_office_the_whole_list_is_offered(self):
        """Un despliegue sin padrón de oficinas sigue cobrando.

        Es el mismo criterio que hace opcional la oficina en el cobro: la sede
        basta para saber qué caja recibió el dinero, y quedarse sin series
        dejaría la ventanilla parada por una tabla que nadie llenó.
        """
        codigos = [sequence.code for sequence in receipt_series_options()]

        self.assertIn("B001", codigos)
        self.assertIn("S002-SPEEDY", codigos)

    def test_an_office_outside_the_padron_falls_back_to_the_whole_list(self):
        """Una ventanilla que el padrón no nombra no se queda muda."""
        recien_creada = Office.objects.create(
            branch=self.branch,
            code="SED01-NUEVA",
            name="Ventanilla nueva",
        )

        codigos = [
            sequence.code
            for sequence in receipt_series_options(office=recien_creada)
        ]

        self.assertIn("B001", codigos)

    def test_the_screen_only_offers_the_books_of_the_active_office(self):
        self.atender_desde("JAUJA-CAJAS")

        response = self.client.get(
            reverse("payments:register", args=[self.customer.pk])
        )
        codigos = [
            sequence.code for sequence in response.context["receipt_series"]
        ]

        self.assertIn("B003-CLA", codigos)
        self.assertNotIn("S010-VELOCIDAD", codigos)

    def test_a_book_from_another_office_is_refused(self):
        """El guardia es el servidor, no el desplegable.

        Que la opción no esté en la lista pintada no basta: el POST se puede
        armar a mano. Cobrar desde Jauja Cajas con un block del Local
        Principal emitiría un número sobre papel que esa ventanilla no tiene.
        """
        self.atender_desde("JAUJA-CAJAS")

        emitidos = Receipt.objects.count()

        response = self.client.post(
            reverse("payments:register", args=[self.customer.pk]),
            {
                "amount": "50.00",
                "method": Payment.Method.CASH,
                "settled": "1",
                "series": "S010-VELOCIDAD",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("series", response.context["form"].errors)
        self.assertEqual(Receipt.objects.count(), emitidos)

    def test_the_screen_opens_on_the_first_book_of_that_office(self):
        """El talonario propuesto es el de la ventanilla, no el de la lista global."""
        self.atender_desde("JAUJA-CAJAS")

        response = self.client.get(
            reverse("payments:register", args=[self.customer.pk])
        )

        self.assertEqual(response.context["form"]["series"].value(), "B003-CLA")
