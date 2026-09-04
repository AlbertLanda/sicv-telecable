from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.customers.forms import CustomerAddressForm
from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.services.annexes import create_annex_adjustment_work_order
from apps.services.forms import SubscriptionCreateForm
from apps.services.models import (
    Plan,
    ServiceType,
    Subscription,
    SubscriptionAnnexAdjustment,
)
from apps.work_orders.models import OrderResult, WorkOrder


User = get_user_model()


class CommercialServiceRulesTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="TST", name="Sede Test Comercial")
        self.zone = Zone.objects.create(branch=self.branch, name="Zona Centro")
        self.customer = Customer.objects.create(
            code="TST01-A0000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="12345678",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Prueba",
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Prueba 100",
            district="Huancayo",
            electrical_supply_code="123456789",
            is_primary=True,
        )
        self.other_address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Prueba 200",
            district="Huancayo",
            electrical_supply_code="987654321",
            is_primary=False,
        )

        self.internet = ServiceType.objects.create(
            code="INTERNET-TEST",
            name="Internet Test",
            supports_tv_annexes=False,
        )
        self.internet_plan = Plan.objects.create(
            service_type=self.internet,
            code="INT-100",
            name="Internet 100",
            monthly_price=Decimal("60.00"),
        )
        self.duo = ServiceType.objects.create(
            code="DUO-TEST",
            name="DUO Test",
            supports_tv_annexes=True,
            annex_installation_price=Decimal("5.00"),
            annex_monthly_price=Decimal("5.00"),
        )
        self.duo_plan = Plan.objects.create(
            service_type=self.duo,
            code="DUO-400",
            name="DUO 400",
            monthly_price=Decimal("80.00"),
            included_tv_points=2,
        )

    def test_alta_domicilio_ya_no_solicita_numero_de_medidor(self):
        form = CustomerAddressForm()
        self.assertNotIn("meter_number", form.fields)
        self.assertIn("electrical_supply_code", form.fields)

    def test_duo_cinco_tv_calcula_dos_cortesias_y_tres_anexos(self):
        form = SubscriptionCreateForm(
            data={
                "address": self.address.pk,
                "service_type": self.duo.pk,
                "plan": self.duo_plan.pk,
                "billing_cycle": 1,
                "tv_count": 5,
            },
            customer=self.customer,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.calculated_initial_courtesy_count, 2)
        self.assertEqual(form.calculated_annex_count, 3)

    def test_una_tv_en_alta_no_deja_segunda_cortesia_pendiente(self):
        form = SubscriptionCreateForm(
            data={
                "address": self.address.pk,
                "service_type": self.duo.pk,
                "plan": self.duo_plan.pk,
                "billing_cycle": 1,
                "tv_count": 1,
            },
            customer=self.customer,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.calculated_initial_courtesy_count, 1)
        self.assertEqual(form.calculated_annex_count, 0)

    def test_internet_no_admite_cantidad_de_tv(self):
        form = SubscriptionCreateForm(
            data={
                "address": self.address.pk,
                "service_type": self.internet.pk,
                "plan": self.internet_plan.pk,
                "billing_cycle": 1,
                "tv_count": 3,
            },
            customer=self.customer,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("tv_count", form.errors)

    def test_no_permite_mismo_servicio_abierto_en_mismo_domicilio(self):
        Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.internet,
            plan=self.internet_plan,
            service_number=1,
            status=Subscription.Status.ACTIVE,
        )
        form = SubscriptionCreateForm(
            data={
                "address": self.address.pk,
                "service_type": self.internet.pk,
                "plan": self.internet_plan.pk,
                "billing_cycle": 1,
            },
            customer=self.customer,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("service_type", form.errors)

    def test_mismo_tipo_de_servicio_si_puede_ir_a_otro_domicilio(self):
        Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.internet,
            plan=self.internet_plan,
            service_number=1,
            status=Subscription.Status.ACTIVE,
        )
        form = SubscriptionCreateForm(
            data={
                "address": self.other_address.pk,
                "service_type": self.internet.pk,
                "plan": self.internet_plan.pk,
                "billing_cycle": 1,
            },
            customer=self.customer,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_costos_de_tres_anexos_usan_snapshot_real(self):
        subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.duo,
            plan=self.duo_plan,
            service_number=1,
            initial_tv_courtesy_granted=2,
            annex_count=3,
            base_monthly_fee=Decimal("80.00"),
        )
        self.assertEqual(subscription.included_tv_points, 2)
        self.assertEqual(subscription.total_tv_points, 5)
        self.assertEqual(subscription.annex_installation_charge, Decimal("15.00"))
        self.assertEqual(subscription.annex_monthly_charge, Decimal("15.00"))
        self.assertEqual(subscription.total_monthly_price, Decimal("95.00"))

    def test_catalogos_estan_habilitados_en_admin(self):
        self.assertTrue(admin.site.is_registered(ServiceType))
        self.assertTrue(admin.site.is_registered(Plan))
        self.assertTrue(admin.site.is_registered(Zone))


class SubscriptionCreateViewRulesTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="VIE", name="Sede View")
        self.customer = Customer.objects.create(
            code="VIE01-A0000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="87654321",
            person_type=Customer.PersonType.NATURAL,
            first_name="Vista",
            paternal_surname="Prueba",
        )
        self.address_1 = CustomerAddress.objects.create(
            customer=self.customer,
            address="Av. Uno 1",
            district="Huancayo",
            is_primary=True,
        )
        self.address_2 = CustomerAddress.objects.create(
            customer=self.customer,
            address="Av. Dos 2",
            district="Huancayo",
            is_primary=False,
        )
        self.service_type = ServiceType.objects.create(
            code="DUO-VIEW",
            name="DUO View",
            supports_tv_annexes=True,
        )
        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="DUO-VIEW-PLAN",
            name="DUO View Plan",
            monthly_price=Decimal("80.00"),
            included_tv_points=2,
        )
        self.user = User.objects.create_user(
            username="atc_comercial",
            password="test-password",
            role=User.Role.ATC,
            branch=self.branch,
        )
        self.client.force_login(self.user)
        self.url = reverse(
            "services:subscription_create",
            kwargs={"customer_pk": self.customer.pk},
        )

    def _post(self, address):
        return self.client.post(
            self.url,
            {
                "address": address.pk,
                "service_type": self.service_type.pk,
                "plan": self.plan.pk,
                "billing_cycle": 1,
                "tv_count": 5,
            },
        )

    def test_numero_de_servicio_es_automatico_y_snapshot_se_guarda(self):
        response = self._post(self.address_1)
        self.assertEqual(response.status_code, 302)
        first = Subscription.objects.get(address=self.address_1)
        self.assertEqual(first.service_number, 1)
        self.assertEqual(first.initial_tv_courtesy_granted, 2)
        self.assertEqual(first.annex_count, 3)
        self.assertEqual(first.base_monthly_fee, Decimal("80.00"))

        response = self._post(self.address_2)
        self.assertEqual(response.status_code, 302)
        second = Subscription.objects.get(address=self.address_2)
        self.assertEqual(second.service_number, 2)
        self.assertEqual(second.initial_tv_courtesy_granted, 2)
        self.assertEqual(second.annex_count, 3)


class AnnexAdjustmentDomainTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="ANX", name="Sede Anexos")
        self.customer = Customer.objects.create(
            code="AN01-A0000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="11223344",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Anexos",
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            address="Jr. Anexos 1",
            district="Huancayo",
        )
        self.service_type = ServiceType.objects.create(
            code="CABLE-ANX",
            name="Cable Anexos",
            supports_tv_annexes=True,
            annex_installation_price=Decimal("5.00"),
            annex_monthly_price=Decimal("5.00"),
        )
        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="CABLE-ANX-PLAN",
            name="Cable Base",
            monthly_price=Decimal("50.00"),
            included_tv_points=2,
        )
        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            service_number=1,
            status=Subscription.Status.ACTIVE,
            initial_tv_courtesy_granted=2,
            annex_count=3,
            base_monthly_fee=Decimal("50.00"),
        )
        self.user = User.objects.create_user(
            username="atc_anexos",
            password="test-password",
            role=User.Role.ATC,
            branch=self.branch,
        )

    def test_aumento_crea_ot_sin_cambiar_suscripcion_hasta_exito(self):
        order = create_annex_adjustment_work_order(
            subscription=self.subscription,
            operation=SubscriptionAnnexAdjustment.Operation.ADD,
            quantity=2,
            created_by=self.user,
        )
        adjustment = order.annex_adjustment
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.annex_count, 3)
        self.assertEqual(adjustment.previous_annex_count, 3)
        self.assertEqual(adjustment.target_annex_count, 5)
        self.assertEqual(adjustment.installation_charge, Decimal("10.00"))
        self.assertEqual(adjustment.monthly_delta, Decimal("10.00"))
        self.assertEqual(adjustment.monthly_charge_after, Decimal("25.00"))

        success = OrderResult.objects.get(order_type__code="TV_ANNEX", code="COMPLETED")
        order.result = success
        order.status = WorkOrder.Status.LIQUIDATED
        order.save(update_fields=["result", "status", "updated_at"])
        self.subscription.refresh_from_db()
        adjustment.refresh_from_db()
        self.assertEqual(self.subscription.annex_count, 5)
        self.assertIsNotNone(adjustment.applied_at)

    def test_retiro_no_genera_costo_unico(self):
        order = create_annex_adjustment_work_order(
            subscription=self.subscription,
            operation=SubscriptionAnnexAdjustment.Operation.REMOVE,
            quantity=2,
            created_by=self.user,
        )
        adjustment = order.annex_adjustment
        self.assertEqual(adjustment.target_annex_count, 1)
        self.assertEqual(adjustment.installation_charge, Decimal("0.00"))
        self.assertEqual(adjustment.monthly_delta, Decimal("-10.00"))
        self.assertEqual(adjustment.monthly_charge_after, Decimal("5.00"))

    def test_resultado_no_exitoso_no_modifica_anexos(self):
        order = create_annex_adjustment_work_order(
            subscription=self.subscription,
            operation=SubscriptionAnnexAdjustment.Operation.REMOVE,
            quantity=1,
            created_by=self.user,
        )
        failed = OrderResult.objects.get(order_type__code="TV_ANNEX", code="NOT_COMPLETED")
        order.result = failed
        order.status = WorkOrder.Status.LIQUIDATED
        order.save(update_fields=["result", "status", "updated_at"])
        self.subscription.refresh_from_db()
        adjustment = order.annex_adjustment
        adjustment.refresh_from_db()
        self.assertEqual(self.subscription.annex_count, 3)
        self.assertIsNone(adjustment.applied_at)
