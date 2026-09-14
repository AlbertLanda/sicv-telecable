"""Las cifras de la cabecera del abonado.

La cabecera se pinta igual en las seis pestañas del abonado y en el alta de
órdenes, así que lo que diga aquí se dice en todas. Por eso se prueba el tag y
no cada pantalla: una cifra mal resuelta se repetiría seis veces.

Hereda el escenario de cobranza -abonado con suscripción activa y política de
cobro- porque la deuda sale de `apps.payments` y montarlo de nuevo aquí daría
dos versiones del mismo abonado que podrían separarse.
"""

from datetime import date
from decimal import Decimal

from apps.customers.templatetags.customer_ui import customer_hero
from apps.payments.models import Charge
from apps.payments.tests.base import PaymentsTestCase
from apps.services.models import BillingPolicy, Subscription


class CabeceraDelAbonadoTests(PaymentsTestCase):
    def cifras(self):
        return customer_hero(self.customer)

    def deber(self, amount="50.00", due_date=date(2026, 1, 31)):
        """Un cargo ya vencido: sin pronto pago que descontar del saldo."""
        return Charge.objects.create(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.MONTHLY,
            amount=Decimal(amount),
            due_date=due_date,
        )

    def test_the_header_states_what_the_customer_owes(self):
        """Estaba solo dentro de la pestaña Deuda.

        Atender desde cualquier otra cara -órdenes, servicios, comprobantes-
        obligaba a cambiar de pantalla para saber si el abonado debe.
        """
        self.deber("50.00")
        self.deber("30.00")

        self.assertEqual(self.cifras()["debt_total"], Decimal("80.00"))

    def test_a_customer_without_debt_shows_zero(self):
        """Cero y no vacío: la cabecera responde «no debe», que no es lo
        mismo que no haber mirado."""
        self.assertEqual(self.cifras()["debt_total"], Decimal("0"))

    def aniversario(self):
        """Política por aniversario: vence el día en que se instaló."""
        return BillingPolicy.objects.create(
            code="ANIVERSARIO",
            name="Aniversario de instalación",
            billing_mode=BillingPolicy.Mode.ANNIVERSARY,
            discount_amount=10,
            discount_days_before_due=5,
            cut_days_after_due=1,
        )

    def segundo_servicio(self, **kwargs):
        return Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=2,
            **kwargs,
        )

    def test_by_calendar_month_the_cycle_is_the_end_of_the_month(self):
        self.assertEqual(self.cifras()["billing_cycle_label"], "Fin de mes")

    def test_by_anniversary_the_cycle_is_the_day_it_was_installed(self):
        """Es la fecha que el abonado tiene interiorizada, la misma que usa
        `monthly_due_date` al emitir la mensualidad."""
        self.subscription.billing_policy = self.aniversario()
        self.subscription.save(update_fields=["billing_policy"])

        self.assertEqual(
            self.cifras()["billing_cycle_label"], "Día 15 de cada mes"
        )

    def test_by_anniversary_without_an_installation_date_it_is_month_end(self):
        """Sin fecha de instalación no hay día que anunciar, y el cargo acaba
        venciendo a fin de mes: la cabecera dice lo que va a pasar, no lo que
        la política pretendía."""
        self.subscription.billing_policy = self.aniversario()
        self.subscription.installation_date = None
        self.subscription.save(
            update_fields=["billing_policy", "installation_date"]
        )

        self.assertEqual(self.cifras()["billing_cycle_label"], "Fin de mes")

    def test_two_services_on_different_cycles_do_not_pick_one(self):
        """Dar el vencimiento de un servicio como si fuera el del abonado
        diría algo falso del otro, y la cabecera es donde nadie va a
        comprobarlo."""
        self.segundo_servicio(
            billing_policy=self.aniversario(),
            installation_date=date(2026, 3, 8),
        )

        self.assertEqual(self.cifras()["billing_cycle_label"], "Varios")

    def test_two_services_on_the_same_cycle_say_the_cycle(self):
        self.segundo_servicio(
            billing_policy=self.policy,
            installation_date=date(2026, 3, 8),
        )

        self.assertEqual(self.cifras()["billing_cycle_label"], "Fin de mes")

    def test_a_cancelled_service_does_not_lend_its_cycle(self):
        """El contador de al lado cuenta servicios activos; el ciclo sale de
        los mismos, o la cabecera diría dos cosas de distinta población."""
        self.subscription.status = Subscription.Status.CANCELLED
        self.subscription.save(update_fields=["status"])

        cifras = self.cifras()

        self.assertEqual(cifras["active_subscription_count"], 0)
        self.assertEqual(cifras["billing_cycle_label"], "")

    def test_a_service_without_a_billing_policy_announces_nothing(self):
        """Sin política no se emite mensualidad -`build_monthly_charge`
        devuelve None-, así que tampoco hay ciclo que anunciar. La plantilla
        lo dice como «No registrado»; inventar «Fin de mes» daría por cierto
        un vencimiento que nadie contrató."""
        self.subscription.billing_policy = None
        self.subscription.save(update_fields=["billing_policy"])

        self.assertEqual(self.cifras()["billing_cycle_label"], "")
