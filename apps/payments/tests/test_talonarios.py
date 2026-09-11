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

from apps.organization.context_processors import ACTIVE_OFFICE_SESSION_KEY
from apps.organization.models import Office
from apps.payments.models import Charge, Payment, Receipt, ReceiptSequence
from apps.payments.services import register_payment
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

        Guardarlo tal cual como «último emitido» saltaría el 0041314: el
        primer recibo de B001 saldría 0041315 y el talonario de papel y el
        sistema dejarían de coincidir desde el primer cobro.
        """
        esperados = {
            "B001": 41314,
            "B002": 31981,
            "F001": 8323,
            "F002": 5597,
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

        self.assertEqual(receipt.number, 41314)
        self.assertEqual(receipt.series, "B001")
        self.assertEqual(receipt.full_number, "B001-041314")

    def test_the_next_one_continues(self):
        self.cobrar(series="B001")
        _, receipt = self.cobrar(series="B001")

        self.assertEqual(receipt.number, 41315)

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
        """Saltar del 41314 al 99000 no deja el correlativo detrás.

        Si se quedara donde estaba, el siguiente cobro propondría 41315 y
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

        self.assertIn('data-numero="41314"', body)
        self.assertIn('data-numero="267"', body)

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
        self.assertEqual(campo.value(), 41314)

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

        self.assertEqual(receipt.full_number, "S010-000267")
        self.assertEqual(Receipt.objects.filter(sequence__code="S010-RED-OPTICA").count(), 1)
