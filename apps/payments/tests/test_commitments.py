"""
Compromiso de pago: aplaza el corte sin mover el saldo.

Lo que se fija aquí es que el compromiso **no** cancele deuda. Es la
confusión que haría perder dinero: si conceder un compromiso descontara el
saldo, el abonado quedaría al día sin haber pagado nada.
"""

import re
from datetime import date, timedelta
from functools import partial
from io import BytesIO
from unittest.mock import patch
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.template.defaultfilters import date as format_date
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer
from apps.payments.board import DATE_FORMAT
from apps.payments.models import Charge, PaymentCommitment
from apps.payments.services import (
    grant_commitment,
    register_payment,
)
from apps.payments.tests.base import PaymentsTestCase


class CommitmentTestCase(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.today = timezone.localdate()

        self.overdue = self.make_charge(
            description="Mensualidad vencida",
            due_date=self.today - timedelta(days=20),
        )
        self.next_one = self.make_charge(
            description="Mensualidad del mes",
            due_date=self.today + timedelta(days=10),
        )

    def make_charge(self, **overrides):
        data = {
            "customer": self.customer,
            "subscription": None,
            "concept": Charge.Concept.OTHER,
            "amount": Decimal("80.00"),
        }
        data.update(overrides)

        return Charge.objects.create(**data)

    def grant(self, charges=None, **kwargs):
        kwargs.setdefault("committed_date", self.today + timedelta(days=7))
        kwargs.setdefault("reason", "El abonado cobra el viernes.")

        return grant_commitment(
            customer=self.customer,
            charges=charges if charges is not None else [self.overdue],
            user=self.cashier,
            **kwargs,
        )


def row_of(body, charge):
    """El renglón de la tabla de deuda que lleva la casilla de `charge`."""
    casilla = re.search(
        r'name="charges"\s+value="%s"' % charge.pk, body
    )
    assert casilla, f"la tabla no ofrece la casilla del cargo {charge.pk}"

    inicio = body.rindex("<tr", 0, casilla.start())
    return body[inicio : body.index("</tr>", casilla.end())]


class CommitmentGrantTests(CommitmentTestCase):
    def test_it_does_not_cancel_the_debt(self):
        """Comprometerse no es pagar.

        La deuda sigue siendo la misma: lo único que cambia es que el cargo
        deja de empujar al corte.
        """
        self.grant()

        self.overdue.refresh_from_db()

        self.assertEqual(self.overdue.status, Charge.Status.PENDING)
        self.assertEqual(self.overdue.balance, Decimal("80.00"))

    def test_the_committed_charge_is_protected_from_the_cut(self):
        self.grant()

        self.overdue.refresh_from_db()

        self.assertTrue(self.overdue.is_protected_from_cut())
        self.assertFalse(self.next_one.is_protected_from_cut())

    def test_without_an_explicit_amount_it_commits_the_full_balance(self):
        commitment = self.grant(charges=[self.overdue, self.next_one])

        self.assertEqual(commitment.amount, Decimal("160.00"))

    def test_the_abonado_can_commit_to_less_than_the_balance(self):
        """Se compromete por lo que puede, no por lo que debe.

        Registrar solo el total forzaría a inventar un acuerdo distinto del
        que realmente se hizo en ventanilla.
        """
        commitment = self.grant(amount=Decimal("50.00"))

        self.assertEqual(commitment.amount, Decimal("50.00"))

    def test_committing_more_than_the_balance_is_rejected(self):
        with self.assertRaises(ValidationError) as error:
            self.grant(amount=Decimal("500.00"))

        self.assertIn("supera el saldo", str(error.exception))

    def test_a_past_date_is_rejected(self):
        """Un plazo ya vencido no aplaza ningún corte."""
        with self.assertRaises(ValidationError) as error:
            self.grant(committed_date=self.today - timedelta(days=1))

        self.assertIn("futura", str(error.exception))

    def test_without_charges_it_is_rejected(self):
        """El compromiso protege cargos concretos, no la deuda futura.

        Dejarlo abierto le daría protección sobre meses que todavía no
        existían cuando se comprometió.
        """
        with self.assertRaises(ValidationError) as error:
            self.grant(charges=[])

        self.assertIn("al menos un cargo", str(error.exception))

    def test_a_note_is_no_longer_required(self):
        """«Observaciones» dejó de exigirse.

        Se llamaba «motivo» y era obligatorio: aplazar el corte de quien ya
        debe es una decisión que alguien tiene que poder explicar. El
        formulario del sistema que se reemplaza lo pide como observaciones y no
        lo exige, y al adoptar ese formulario se adoptó también su regla.

        Lo que sigue en pie es quién responde: `authorized_by` guarda al que
        autoriza, aparte del que lo teclea.
        """
        commitment = self.grant(reason="   ")

        self.assertEqual(commitment.reason, "")

    def test_a_paid_charge_cannot_be_committed(self):
        register_payment(
            customer=self.customer,
            amount=Decimal("80.00"),
            method="CASH",
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.overdue, Decimal("80.00"))],
        )
        self.overdue.refresh_from_db()

        with self.assertRaises(ValidationError) as error:
            self.grant()

        self.assertIn("saldo pendiente", str(error.exception))

    def test_a_charge_of_another_customer_is_rejected(self):
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
            amount=Decimal("50.00"),
            due_date=self.today,
        )

        with self.assertRaises(ValidationError):
            self.grant(charges=[foreign])


class CommitmentLifecycleTests(CommitmentTestCase):
    def test_paying_the_charges_fulfills_it(self):
        commitment = self.grant()

        register_payment(
            customer=self.customer,
            amount=Decimal("80.00"),
            method="CASH",
            branch=self.branch,
            user=self.cashier,
            allocations=[(self.overdue, Decimal("80.00"))],
        )

        self.assertEqual(commitment.evaluate(), PaymentCommitment.Status.FULFILLED)

    def test_the_date_passing_with_a_balance_breaks_it(self):
        """Se rompe por el paso del tiempo, no por una acción de nadie.

        Por eso se reevalúa al leerlo: sin esto, uno vencido seguiría
        figurando como vigente hasta que alguien lo tocara.
        """
        commitment = self.grant(committed_date=self.today + timedelta(days=1))

        later = self.today + timedelta(days=5)

        self.assertEqual(
            commitment.evaluate(day=later), PaymentCommitment.Status.BROKEN
        )

    def test_it_stays_active_while_the_date_has_not_arrived(self):
        commitment = self.grant()

        self.assertEqual(commitment.evaluate(), PaymentCommitment.Status.ACTIVE)

    def test_an_expired_commitment_stops_protecting_the_charge(self):
        self.grant(committed_date=self.today + timedelta(days=1))

        self.overdue.refresh_from_db()

        self.assertTrue(self.overdue.is_protected_from_cut(on=self.today))
        self.assertFalse(
            self.overdue.is_protected_from_cut(on=self.today + timedelta(days=5))
        )

    def test_cancelling_it_returns_the_charge_to_the_cut_path(self):
        commitment = self.grant()

        commitment.cancel(user=self.cashier, reason="El abonado se retractó.")
        self.overdue.refresh_from_db()

        self.assertEqual(commitment.status, PaymentCommitment.Status.CANCELLED)
        self.assertFalse(self.overdue.is_protected_from_cut())
        self.assertIn("se retractó", commitment.reason)

    def test_it_is_not_cancelled_twice(self):
        commitment = self.grant()
        commitment.cancel(user=self.cashier, reason="Primera anulación.")

        with self.assertRaises(ValidationError):
            commitment.cancel(user=self.cashier, reason="Segunda.")


class CommitmentWebTests(CommitmentTestCase):
    def setUp(self):
        super().setUp()

        self.viewer = self.make_user("consulta1", permissions=["view_charge"])
        self.granter = self.make_user(
            "supervisor1",
            permissions=["view_charge", "grant_paymentcommitment"],
        )

    def url(self):
        return reverse("payments:commitment_create", args=[self.customer.pk])

    def test_viewing_the_debt_does_not_grant_committing(self):
        """Aplazar un corte es una decisión comercial, no una consulta."""
        self.login(self.viewer)

        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_the_debt_board_hides_the_button_without_permission(self):
        self.login(self.viewer)

        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertFalse(response.context["can_grant_commitment"])
        self.assertNotContains(response, self.url())

    def test_the_debt_board_offers_the_button_to_who_may_grant(self):
        self.login(self.granter)

        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertTrue(response.context["can_grant_commitment"])
        self.assertContains(response, self.url())

    def test_selected_charges_are_committed(self):
        self.login(self.granter)

        response = self.client.post(
            self.url(),
            {
                "charges": [self.overdue.pk],
                "committed_date": (self.today + timedelta(days=5)).isoformat(),
                "reason": "El abonado cobra el viernes.",
            },
        )

        commitment = PaymentCommitment.objects.get()

        self.assertRedirects(
            response, reverse("payments:debt", args=[self.customer.pk])
        )
        self.assertEqual(list(commitment.charges.all()), [self.overdue])
        self.assertEqual(commitment.granted_by, self.granter)

    def test_submitting_without_selecting_a_charge_reports_it(self):
        self.login(self.granter)

        response = self.client.post(
            self.url(),
            {
                "committed_date": (self.today + timedelta(days=5)).isoformat(),
                "reason": "Sin elegir nada.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "al menos un cargo")
        self.assertFalse(PaymentCommitment.objects.exists())

    def test_a_past_date_does_not_create_the_commitment(self):
        self.login(self.granter)

        response = self.client.post(
            self.url(),
            {
                "charges": [self.overdue.pk],
                "committed_date": (self.today - timedelta(days=1)).isoformat(),
                "reason": "Fecha ya pasada.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PaymentCommitment.objects.exists())

    def test_the_board_shows_the_active_commitment(self):
        commitment = self.grant()
        self.login(self.granter)

        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertEqual(len(response.context["active_commitments"]), 1)
        self.assertContains(response, ">Compromiso</a>")
        self.assertContains(
            response, format_date(commitment.committed_date, DATE_FORMAT)
        )

    def test_the_commitment_is_read_in_the_row_being_marked(self):
        """El compromiso se lee en la fila misma que se va a marcar.

        Mientras siga en pie cambia lo que el operador puede decirle al
        abonado -esa deuda no empuja al corte hasta la fecha acordada-. Al pie
        se leía después de haber marcado qué cobrar; en una tarjeta encima,
        había que cruzarla a ojo con la fila. Como estado de la fila, se lee
        junto a la casilla.
        """
        self.grant()
        self.login(self.granter)

        body = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        ).content.decode()

        self.assertIn("Compromiso ", row_of(body, self.overdue))
        self.assertNotIn("Compromiso ", row_of(body, self.next_one))

    def test_cancelling_from_the_board_requires_the_permission(self):
        commitment = self.grant()
        self.login(self.viewer)

        response = self.client.post(
            reverse("payments:commitment_cancel", args=[commitment.pk])
        )
        commitment.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(commitment.status, PaymentCommitment.Status.ACTIVE)


class CompromisoEnLaTablaTests(CommitmentTestCase):
    """El compromiso vigente es el estado de los cargos que protege.

    Iba en una tarjeta encima de la tabla. Con varias acumuladas empujaban la
    primera deuda por debajo del pliegue, y había que cruzar a ojo la tarjeta
    con las filas que cubría. No tiene fila propia: repetiría el monto de los
    cargos que cubre y la tabla parecería deber el doble.
    """

    def setUp(self):
        super().setUp()

        self.granter = self.make_user(
            "supervisor7",
            permissions=["view_charge", "grant_paymentcommitment"],
        )
        self.login(self.granter)

    def board(self):
        return self.client.get(reverse("payments:debt", args=[self.customer.pk]))

    def detail_url(self, commitment):
        return reverse(
            "payments:commitment_detail",
            kwargs={"pk": self.customer.pk, "commitment_pk": commitment.pk},
        )

    def test_without_commitment_the_charge_shows_its_own_status(self):
        body = self.board().content.decode()

        self.assertIn("Vencido", row_of(body, self.overdue))
        self.assertIn("Pendiente", row_of(body, self.next_one))

    def test_the_status_names_the_commitment_and_when_it_pays(self):
        """Qué es, cuándo paga y cuál es."""
        commitment = self.grant()
        renglon = row_of(self.board().content.decode(), self.overdue)

        # La etiqueta solo dice qué es; cuándo paga y cuál es van en el
        # rótulo emergente, a un pase del cursor.
        self.assertIn(">Compromiso</a>", renglon)
        self.assertIn(f"Compromiso de pago {commitment.pk}", renglon)
        self.assertIn(format_date(commitment.committed_date, DATE_FORMAT), renglon)

    def test_the_commitment_takes_the_place_of_the_other_status(self):
        """Un solo estado por fila, y no un segundo renglón.

        La columna de vencimiento llevaba una etiqueta «Compromiso dd/mm/aaaa»
        debajo de la fecha, y al ocupar otra línea hacía esa fila más alta que
        las demás: en una lista larga esa diferencia se lee como si fueran
        bloques distintos. Ahora el vencimiento solo trae su fecha y el
        compromiso reemplaza al «Vencido» en la columna del estado.
        """
        self.grant()
        renglon = row_of(self.board().content.decode(), self.overdue)

        self.assertNotIn("Vencido", renglon)
        self.assertIn(
            f'<td class="tc-date">{format_date(self.overdue.due_date, DATE_FORMAT)}</td>',
            renglon,
        )

    def test_the_status_is_a_real_link_to_the_commitment(self):
        """El estado lleva al compromiso con un enlace de verdad.

        Es un `href` y no un guion: sin JavaScript, o con el teclado, sigue
        llevando a la pantalla completa del compromiso.
        """
        commitment = self.grant()
        renglon = row_of(self.board().content.decode(), self.overdue)

        self.assertIn(f'href="{self.detail_url(commitment)}"', renglon)

    def test_a_cancelled_commitment_stops_being_announced(self):
        commitment = self.grant()
        commitment.cancel(user=self.granter, reason="Se deja sin efecto.")

        renglon = row_of(self.board().content.decode(), self.overdue)

        self.assertIn("Vencido", renglon)
        self.assertNotIn(self.detail_url(commitment), renglon)


class PantallaDelCompromisoTests(CommitmentTestCase):
    """El compromiso concedido tiene su pantalla, a la que lleva el aviso.

    Se llegó a probar con una ventana emergente y se retiró: el aviso lleva
    directo al formulario, que es lo que el operador espera de un enlace.
    """

    def setUp(self):
        super().setUp()

        self.granter = self.make_user(
            "supervisor8",
            permissions=["view_charge", "grant_paymentcommitment"],
        )
        self.login(self.granter)

    def detalle_url(self, commitment):
        return reverse(
            "payments:commitment_detail",
            kwargs={"pk": self.customer.pk, "commitment_pk": commitment.pk},
        )

    def test_the_notice_leads_to_the_commitment_sheet(self):
        commitment = self.grant()

        body = self.client.get(self.detalle_url(commitment)).content.decode()

        self.assertIn(f"Compromiso de pago {commitment.pk}", body)

    def test_the_sheet_shows_the_debt_it_protects(self):
        commitment = self.grant()

        body = self.client.get(self.detalle_url(commitment)).content.decode()

        self.assertIn(self.overdue.description, body)

    def test_the_sheet_is_blocked(self):
        """Un compromiso concedido no se corrige: se anula y se concede otro.

        Mismo criterio que el comprobante emitido, y por eso `disabled` y no
        `readonly`: `readonly` deja el campo enfocable y con aspecto de
        editable, que invita a intentarlo.
        """
        commitment = self.grant()

        body = self.client.get(self.detalle_url(commitment)).content.decode()
        # Se ancla en el marcado y no en el nombre de la clase: «tc-section-body»
        # aparece antes en la hoja de estilos, y el corte se llevaba los campos
        # de la barra superior.
        inicio = body.index('<div class="tc-section-body">')
        ficha = body[inicio : body.index("</section>", inicio)]

        campos = ficha.count("<input") + ficha.count("<textarea")

        self.assertGreater(campos, 0)
        self.assertEqual(campos, ficha.count("disabled"))

    def test_a_commitment_of_another_customer_is_not_found(self):
        """El compromiso se busca dentro del abonado de la dirección.

        Sin acotarlo, poner otro número a mano abriría el compromiso de un
        cliente distinto bajo la ficha de este.
        """
        ajeno = Customer.objects.create(
            code="CLI999",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="11223344",
            first_name="Otra",
            paternal_surname="Persona",
        )
        commitment = self.grant()

        respuesta = self.client.get(
            reverse(
                "payments:commitment_detail",
                kwargs={"pk": ajeno.pk, "commitment_pk": commitment.pk},
            )
        )

        self.assertEqual(respuesta.status_code, 404)

    def test_cancelling_comes_back_to_the_board(self):
        commitment = self.grant()

        respuesta = self.client.post(
            reverse("payments:commitment_cancel", args=[commitment.pk])
        )
        commitment.refresh_from_db()

        self.assertRedirects(
            respuesta, reverse("payments:debt", args=[self.customer.pk])
        )
        self.assertEqual(commitment.status, PaymentCommitment.Status.CANCELLED)


class PlanDeCuotasTests(CommitmentTestCase):
    """Cómo piensa pagar lo comprometido, cuota a cuota.

    El plan es detalle del acuerdo y no otra promesa: la fecha que aplaza el
    corte sigue siendo una sola, la de arriba. Si cada cuota protegiera hasta
    la siguiente, la protección se renovaría sola y un plan de quince cuotas
    dejaría al abonado fuera del corte durante meses sin que nadie lo volviera
    a decidir.
    """

    def cuota(self, numero, monto, dias):
        return (numero, Decimal(monto), self.today + timedelta(days=dias))

    def test_the_plan_is_saved_installment_by_installment(self):
        commitment = self.grant(
            amount=Decimal("60.00"),
            installments=[
                self.cuota(1, "20.00", 7),
                self.cuota(2, "40.00", 21),
            ],
        )

        cuotas = list(commitment.installments.all())

        self.assertEqual([c.number for c in cuotas], [1, 2])
        self.assertEqual(
            [c.amount for c in cuotas], [Decimal("20.00"), Decimal("40.00")]
        )

    def test_blank_rows_are_not_saved(self):
        """Lo normal es llenar dos o tres de las quince filas."""
        commitment = self.grant(
            amount=Decimal("60.00"),
            installments=[
                self.cuota(1, "60.00", 7),
                (2, None, None),
                (3, None, None),
            ],
        )

        self.assertEqual(commitment.installments.count(), 1)

    def test_half_a_row_is_refused_naming_it(self):
        """Media cuota no dice ni cuánto ni cuándo.

        Guardarla dejaría un plan que no se puede seguir, y callarla dejaría al
        operador creyendo que apuntó algo que no quedó.
        """
        with self.assertRaises(ValidationError) as caso:
            self.grant(
                amount=Decimal("60.00"),
                installments=[(1, Decimal("20.00"), None)],
            )

        self.assertIn("cuota 1", " ".join(caso.exception.messages).lower())

    def test_the_plan_cannot_promise_more_than_the_commitment(self):
        """El plan describe cómo se paga lo acordado, no otra cosa.

        Pasarse dejaría el papel diciendo dos cifras distintas sobre el mismo
        acuerdo.
        """
        with self.assertRaises(ValidationError):
            self.grant(
                amount=Decimal("50.00"),
                installments=[
                    self.cuota(1, "30.00", 7),
                    self.cuota(2, "30.00", 21),
                ],
            )

    def test_the_plan_may_add_up_to_less(self):
        """El operador puede dejar apuntadas las primeras y el resto para después."""
        commitment = self.grant(
            amount=Decimal("80.00"),
            installments=[self.cuota(1, "20.00", 7)],
        )

        self.assertEqual(commitment.installments.count(), 1)
        self.assertEqual(commitment.amount, Decimal("80.00"))

    def test_the_installments_do_not_extend_the_protection(self):
        """La fecha que aplaza el corte sigue siendo la de arriba, una sola."""
        commitment = self.grant(
            committed_date=self.today + timedelta(days=5),
            amount=Decimal("60.00"),
            installments=[self.cuota(1, "60.00", 90)],
        )

        self.assertEqual(
            commitment.committed_date, self.today + timedelta(days=5)
        )


class ObservacionesYRepresentanteTests(CommitmentTestCase):
    """Los campos que el formulario del sistema anterior pide y no exige."""

    def test_a_commitment_can_be_granted_without_a_note(self):
        """«Observaciones» dejó de ser obligatorio.

        Se llamaba «motivo» y se exigía; el formulario del sistema que se
        reemplaza lo pide como observaciones y no lo exige, y esa es la regla
        que se adoptó.
        """
        commitment = self.grant(reason="")

        self.assertEqual(commitment.reason, "")

    def test_the_representative_is_recorded(self):
        """El acuerdo lo asume una persona, y puede no ser el titular."""
        commitment = self.grant(
            representative="  Rosa Ravichagua  ",
            representative_document=" 71692678 ",
        )

        self.assertEqual(commitment.representative, "Rosa Ravichagua")
        self.assertEqual(commitment.representative_document, "71692678")


class LaFichaDelCompromisoTests(CommitmentTestCase):
    """Lo que dicen el alta y el compromiso concedido.

    El alta se rediseñó con la forma del cobro -deudas y datos a la
    izquierda, el acuerdo a la derecha-, así que ya no es la ficha del
    concedido campo por campo. Comparten los datos que se comprueban; el alta
    no lleva «Anulado» -un compromiso no nace anulado- y nombra al DNI del
    representante entero.
    """

    #: Las del alta.
    ETIQUETAS_ALTA = [
        "Código",
        "Fecha",
        "Hora",
        "Fecha de pago",
        "Autoriza",
        "Deuda",
        "Total",
        "Cuota 1",
        "Representante",
        "DNI del representante",
        "Observaciones",
    ]

    #: Las del compromiso concedido.
    ETIQUETAS = [
        "Código",
        "Fecha",
        "Hora",
        "Fecha de pago",
        "Autoriza",
        "Deuda",
        "Total",
        "Cuota 1",
        "Representante",
        "DNI de rep.",
        "Observaciones",
        "Anulado",
    ]

    def setUp(self):
        super().setUp()

        self.granter = self.make_user(
            "supervisor9",
            permissions=["view_charge", "grant_paymentcommitment"],
        )
        self.login(self.granter)

    def alta(self, **params):
        return self.client.get(
            reverse("payments:commitment_create", args=[self.customer.pk]),
            {"charges": [self.overdue.pk], **params},
        )

    def test_the_creation_sheet_has_the_fields_of_the_old_system(self):
        body = self.alta().content.decode()

        for etiqueta in self.ETIQUETAS_ALTA:
            with self.subTest(etiqueta=etiqueta):
                self.assertIn(etiqueta, body)

    def test_the_creation_sheet_is_not_born_cancelled(self):
        self.assertNotIn("Anulado", self.alta().content.decode())

    def test_the_creation_sheet_heads_without_the_blue_band(self):
        self.assertNotIn(
            'class="tc-section-head banner"', self.alta().content.decode()
        )

    def test_the_creation_sheet_offers_fifteen_installments(self):
        """Hasta quince, como el formulario que el operador usa a diario."""
        body = self.alta().content.decode()

        self.assertIn("Cuota 15", body)
        self.assertNotIn("Cuota 16", body)

    def test_the_installments_start_switched_off(self):
        """Casi todo compromiso es un solo pago: las cuotas se piden aparte."""
        form = self.alta().context["form"]

        self.assertFalse(form["in_installments"].value())
        self.assertIn('role="switch"', str(form["in_installments"]))

    def test_only_three_rows_show_when_switched_on(self):
        """Las demás se agregan de a una: quince de golpe eran una pared."""
        body = self.alta().content.decode()

        for numero in (1, 2, 3):
            with self.subTest(cuota=numero):
                self.assertIn(f'data-cuota="{numero}" >', body)
        for numero in (4, 15):
            with self.subTest(cuota=numero):
                self.assertIn(f'data-cuota="{numero}" hidden>', body)

    def test_a_row_written_further_down_comes_back_visible(self):
        """Con un error, la cuota siete no puede quedar detrás de «Agregar»."""
        respuesta = self.client.post(
            reverse("payments:commitment_create", args=[self.customer.pk]),
            {
                "charges": [self.overdue.pk],
                "committed_date": "",
                "in_installments": "on",
                "installment_7_amount": "20.00",
            },
        )
        body = respuesta.content.decode()

        self.assertIn('data-cuota="7" >', body)
        self.assertIn('data-cuota="8" hidden>', body)

    def test_the_granted_sheet_repeats_the_same_labels(self):
        commitment = self.grant(
            amount=Decimal("60.00"),
            installments=[(1, Decimal("60.00"), self.today + timedelta(days=7))],
        )

        body = self.client.get(
            reverse(
                "payments:commitment_detail",
                kwargs={
                    "pk": self.customer.pk,
                    "commitment_pk": commitment.pk,
                },
            )
        ).content.decode()

        for etiqueta in self.ETIQUETAS:
            with self.subTest(etiqueta=etiqueta):
                self.assertIn(etiqueta, body)

    def test_the_granted_sheet_only_shows_the_filled_installments(self):
        """Quince filas en blanco dirían que se pactaron quince cuotas."""
        commitment = self.grant(
            amount=Decimal("60.00"),
            installments=[(1, Decimal("60.00"), self.today + timedelta(days=7))],
        )

        body = self.client.get(
            reverse(
                "payments:commitment_detail",
                kwargs={
                    "pk": self.customer.pk,
                    "commitment_pk": commitment.pk,
                },
            )
        ).content.decode()

        self.assertIn("Cuota 1", body)
        self.assertNotIn("Cuota 2", body)

    def test_the_board_sends_the_marked_debt_hidden(self):
        """La deuda se elige en el tablero y aquí solo se lee.

        Sin los campos escondidos el compromiso se concedería sobre nada: la
        ficha ya no trae casillas que manden los cargos.
        """
        body = self.client.get(
            reverse("payments:commitment_create", args=[self.customer.pk]),
            {"charges": [self.overdue.pk]},
        ).content.decode()

        self.assertIn(
            f'<input type="hidden" name="charges" value="{self.overdue.pk}">',
            body,
        )

    def test_granting_from_the_screen_saves_the_plan(self):
        respuesta = self.client.post(
            reverse("payments:commitment_create", args=[self.customer.pk]),
            {
                "charges": [self.overdue.pk],
                "committed_date": (self.today + timedelta(days=10)).isoformat(),
                "amount": "60.00",
                "in_installments": "on",
                "installment_1_amount": "20.00",
                "installment_1_date": (
                    self.today + timedelta(days=5)
                ).isoformat(),
                "installment_2_amount": "40.00",
                "installment_2_date": (
                    self.today + timedelta(days=20)
                ).isoformat(),
                "representative": "Rosa Ravichagua",
                "representative_document": "71692678",
                "reason": "Paga en dos partes.",
            },
        )

        self.assertEqual(respuesta.status_code, 302)

        commitment = PaymentCommitment.objects.get()

        self.assertEqual(commitment.installments.count(), 2)
        self.assertEqual(commitment.representative, "Rosa Ravichagua")

    def test_switched_off_the_written_installments_are_not_saved(self):
        """Lo que se acuerda es lo que se ve: apagado, un solo pago."""
        respuesta = self.client.post(
            reverse("payments:commitment_create", args=[self.customer.pk]),
            {
                "charges": [self.overdue.pk],
                "committed_date": (self.today + timedelta(days=10)).isoformat(),
                "installment_1_amount": "20.00",
                "installment_1_date": (
                    self.today + timedelta(days=5)
                ).isoformat(),
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(PaymentCommitment.objects.get().installments.count(), 0)


class ElPapelDelCompromisoTests(CommitmentTestCase):
    """El compromiso impreso, el que el abonado firma.

    No es un comprobante: no numera caja ni declara impuestos. Es la solicitud
    de prórroga, y por eso acaba en dos líneas de firma en vez de en un
    recuadro de importes.
    """

    def setUp(self):
        super().setUp()

        self.granter = self.make_user(
            "supervisor10",
            permissions=["view_charge", "grant_paymentcommitment"],
        )
        self.login(self.granter)

    def papel(self, commitment):
        """El PDF sin comprimir, para poder leer lo que dibuja."""
        from apps.payments import commitment_pdf

        original = commitment_pdf.SimpleDocTemplate

        with patch.object(
            commitment_pdf,
            "SimpleDocTemplate",
            partial(original, pageCompression=0),
        ):
            buffer = BytesIO()
            commitment_pdf.render_commitment(commitment, buffer)

            return buffer.getvalue()

    def pdf_url(self, commitment):
        return reverse(
            "payments:commitment_pdf",
            kwargs={"pk": self.customer.pk, "commitment_pk": commitment.pk},
        )

    def test_the_screen_offers_the_print_button(self):
        commitment = self.grant()

        body = self.client.get(
            reverse(
                "payments:commitment_detail",
                kwargs={
                    "pk": self.customer.pk,
                    "commitment_pk": commitment.pk,
                },
            )
        ).content.decode()

        self.assertIn(self.pdf_url(commitment), body)
        self.assertIn("Imprimir", body)

    def test_it_comes_back_as_a_pdf(self):
        commitment = self.grant()

        respuesta = self.client.get(self.pdf_url(commitment))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta["Content-Type"], "application/pdf")

    def test_it_says_what_the_paper_says(self):
        commitment = self.grant()
        papel = self.papel(commitment)

        for dato in (
            "COMPROMISO DE PAGO",
            "prorroga",
            "Importe",
            "Vencimiento",
            "Corte",
            "Importe total",
            "Abonado",
            "Representante",
            "Firma del abonado",
            "Autorizado por",
        ):
            with self.subTest(dato=dato):
                self.assertIn(dato.encode("latin-1"), papel)

    def test_the_number_is_padded(self):
        """«Nº 002671», como el papel del sistema anterior."""
        from apps.payments.commitment_pdf import commitment_number

        commitment = self.grant()

        self.assertEqual(len(commitment_number(commitment)), 6)
        self.assertTrue(
            commitment_number(commitment).endswith(str(commitment.pk))
        )

    def test_without_a_plan_it_prints_one_row(self):
        """Sin cuotas, el recuadro dice el total y la fecha del compromiso.

        Dejarlo vacío daría un papel que el abonado firma sin que diga cuánto
        ni cuándo.
        """
        from apps.payments.commitment_pdf import commitment_rows

        commitment = self.grant(amount=Decimal("60.00"))

        self.assertEqual(
            commitment_rows(commitment),
            [(Decimal("60.00"), commitment.committed_date)],
        )

    def test_with_a_plan_it_prints_one_row_per_installment(self):
        from apps.payments.commitment_pdf import commitment_rows

        primera = self.today + timedelta(days=7)
        segunda = self.today + timedelta(days=21)

        commitment = self.grant(
            amount=Decimal("60.00"),
            installments=[
                (1, Decimal("20.00"), primera),
                (2, Decimal("40.00"), segunda),
            ],
        )

        self.assertEqual(
            commitment_rows(commitment),
            [(Decimal("20.00"), primera), (Decimal("40.00"), segunda)],
        )

    def test_the_cut_is_the_day_after_the_due_date(self):
        """Vence el 23 y corta el 24, como en el papel de referencia."""
        from apps.payments.commitment_pdf import DIAS_HASTA_EL_CORTE

        commitment = self.grant(committed_date=self.today + timedelta(days=9))
        papel = self.papel(commitment)

        corte = commitment.committed_date + timedelta(
            days=DIAS_HASTA_EL_CORTE
        )

        self.assertIn(corte.strftime("%d/%m/%Y").encode("latin-1"), papel)

    def test_a_commitment_of_another_customer_cannot_be_printed(self):
        ajeno = Customer.objects.create(
            code="CLI888",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="99887766",
            first_name="Otra",
            paternal_surname="Persona",
        )
        commitment = self.grant()

        respuesta = self.client.get(
            reverse(
                "payments:commitment_pdf",
                kwargs={"pk": ajeno.pk, "commitment_pk": commitment.pk},
            )
        )

        self.assertEqual(respuesta.status_code, 404)

    def test_the_creation_screen_no_longer_lists_past_commitments(self):
        """La tabla de compromisos registrados salió del alta.

        Lo que se está haciendo ahí es conceder uno nuevo; el historial del
        abonado se consulta desde su cuenta.
        """
        self.grant()

        body = self.client.get(
            reverse("payments:commitment_create", args=[self.customer.pk]),
            {"charges": [self.next_one.pk]},
        ).content.decode()

        self.assertNotIn("Compromisos registrados", body)
