from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.services.commercial import (
    build_commercial_quote,
    resolve_plan_tariff,
    validate_plan_commercial_availability,
)
from apps.services.forms import SubscriptionCreateForm
from apps.services.installation_rules import (
    record_installation_material_usage,
    total_installation_excess_charge,
)
from apps.services.models import (
    BillingPolicy,
    CommercialCoverageRule,
    InstallationMaterialRule,
    Plan,
    PlanTariff,
    ServiceType,
)
from apps.work_orders.models import OrderType
from apps.work_orders.services import create_work_order


User = get_user_model()


class BillingPolicyRulesTests(TestCase):
    def test_calendario_ajusta_pronto_pago_en_febrero_y_corta_dia_seis(self):
        policy = BillingPolicy.objects.create(
            code="TEST-CAL",
            name="Calendario test",
            billing_mode=BillingPolicy.Mode.CALENDAR_MONTH,
            discount_amount=Decimal("5.00"),
            discount_deadline_day=29,
            cut_day_next_month=6,
        )
        due = date(2026, 2, 28)
        self.assertEqual(policy.discount_deadline_for(due), date(2026, 2, 28))
        self.assertEqual(policy.cut_date_for(due), date(2026, 3, 6))

    def test_estandar_2026_descuenta_tres_dias_antes_y_corta_al_dia_siguiente(self):
        policy = BillingPolicy.objects.create(
            code="TEST-ANN",
            name="Aniversario test",
            billing_mode=BillingPolicy.Mode.ANNIVERSARY,
            discount_amount=Decimal("10.00"),
            discount_days_before_due=3,
            cut_days_after_due=1,
        )
        due = date(2026, 2, 14)
        self.assertEqual(policy.discount_deadline_for(due), date(2026, 2, 11))
        self.assertEqual(policy.cut_date_for(due), date(2026, 2, 15))


class CommercialTariffAndCoverageTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="GEO", name="Sede Geo")
        self.zone = Zone.objects.create(branch=self.branch, name="Zona Especial")
        self.customer = Customer.objects.create(
            code="GEO01-A0000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="44556677",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Geo",
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Geo 100",
            district="Test",
            is_primary=True,
        )
        self.internet = ServiceType.objects.create(code="INT-GEO", name="Internet Geo")
        self.standard = Plan.objects.create(
            service_type=self.internet,
            code="STD-2026",
            name="Estándar 400",
            generation=2026,
            commercial_category=Plan.Category.STANDARD,
            speed_mbps=400,
            monthly_price=Decimal("69.00"),
        )
        self.economic = Plan.objects.create(
            service_type=self.internet,
            code="ECO-2026",
            name="Económico 200",
            generation=2026,
            commercial_category=Plan.Category.ECONOMIC,
            speed_mbps=200,
            monthly_price=Decimal("50.00"),
        )

    def test_tarifa_de_zona_prevalece_sobre_tarifa_general_de_sede(self):
        PlanTariff.objects.create(
            plan=self.standard,
            branch=self.branch,
            installation_fee=Decimal("50.00"),
            monthly_fee=Decimal("50.00"),
            valid_from=date(2026, 1, 1),
        )
        zone_tariff = PlanTariff.objects.create(
            plan=self.standard,
            branch=self.branch,
            zone=self.zone,
            installation_fee=Decimal("20.00"),
            monthly_fee=Decimal("35.00"),
            valid_from=date(2026, 1, 1),
        )
        self.assertEqual(
            resolve_plan_tariff(plan=self.standard, address=self.address, on_date=date(2026, 9, 4)),
            zone_tariff,
        )

    def test_categoria_obligatoria_bloquea_otro_plan(self):
        CommercialCoverageRule.objects.create(
            generation=2026,
            commercial_category=Plan.Category.STANDARD,
            branch=self.branch,
            zone=self.zone,
            availability=CommercialCoverageRule.Availability.REQUIRED,
            valid_from=date(2026, 1, 1),
        )
        validate_plan_commercial_availability(
            plan=self.standard,
            address=self.address,
            on_date=date(2026, 9, 4),
        )
        with self.assertRaises(ValidationError):
            validate_plan_commercial_availability(
                plan=self.economic,
                address=self.address,
                on_date=date(2026, 9, 4),
            )

    def test_plan_que_exige_tarifa_no_se_vende_si_no_hay_tarifa_vigente(self):
        self.standard.requires_geographic_tariff = True
        self.standard.save(update_fields=["requires_geographic_tariff"])
        with self.assertRaises(ValidationError):
            build_commercial_quote(
                plan=self.standard,
                address=self.address,
                on_date=date(2026, 9, 4),
            )


class CableInitialPaymentTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="CAB", name="Sede Cable")
        self.customer = Customer.objects.create(
            code="CAB01-A0000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="66778899",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Cable",
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            address="Av. Cable 1",
            district="Jauja",
            is_primary=True,
        )
        self.cable = ServiceType.objects.create(
            code="CABLE-PAY",
            name="Cable",
            supports_tv_annexes=True,
            annex_installation_price=Decimal("5.00"),
            annex_monthly_price=Decimal("5.00"),
        )
        self.policy = BillingPolicy.objects.create(
            code="CAB-CAL",
            name="Cable calendario",
            billing_mode=BillingPolicy.Mode.CALENDAR_MONTH,
            discount_amount=0,
            cut_day_next_month=6,
            first_month_required=True,
        )
        self.plan = Plan.objects.create(
            service_type=self.cable,
            code="CABLE-BASE",
            name="Cable residencial",
            billing_policy=self.policy,
            included_tv_points=2,
            requires_geographic_tariff=True,
        )
        PlanTariff.objects.create(
            plan=self.plan,
            branch=self.branch,
            installation_fee=Decimal("50.00"),
            monthly_fee=Decimal("50.00"),
            valid_from=date(2026, 1, 1),
        )

    def test_cinco_tv_requieren_130_soles_para_instalar(self):
        form = SubscriptionCreateForm(
            data={
                "address": self.address.pk,
                "service_type": self.cable.pk,
                "plan": self.plan.pk,
                "tv_count": 5,
            },
            customer=self.customer,
        )
        self.assertTrue(form.is_valid(), form.errors)
        quote = form.selected_quote
        self.assertEqual(form.calculated_initial_courtesy_count, 2)
        self.assertEqual(form.calculated_annex_count, 3)
        initial_total = (
            quote["installation_fee"]
            + quote["monthly_fee"]
            + Decimal("15.00")
            + Decimal("15.00")
        )
        self.assertEqual(initial_total, Decimal("130.00"))


class InstallationExcessRulesTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="MAT", name="Sede Material")
        self.customer = Customer.objects.create(
            code="MAT01-A0000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="99887766",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Material",
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            address="Jr. Material 1",
            district="Jauja",
        )
        self.internet = ServiceType.objects.create(code="INT-MAT", name="Internet Material")
        self.plan = Plan.objects.create(
            service_type=self.internet,
            code="INT-MAT-PLAN",
            name="Internet Material",
            monthly_price=Decimal("60.00"),
        )
        from apps.services.models import Subscription
        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.internet,
            plan=self.plan,
            service_number=1,
            base_monthly_fee=Decimal("60.00"),
        )
        self.user = User.objects.create_user(
            username="material_user",
            password="test-password",
            role=User.Role.ATC,
            branch=self.branch,
        )
        self.order_type, _ = OrderType.objects.get_or_create(
            code="INSTALLATION",
            defaults={"name": "Instalación", "is_active": True},
        )
        self.order = create_work_order(
            subscription=self.subscription,
            order_type=self.order_type,
            created_by=self.user,
        )
        InstallationMaterialRule.objects.create(
            material=InstallationMaterialRule.Material.UTP,
            service_type=self.internet,
            free_meters=Decimal("30.00"),
            excess_price_per_meter=Decimal("2.00"),
            valid_from=date(2026, 1, 1),
        )
        InstallationMaterialRule.objects.create(
            material=InstallationMaterialRule.Material.DROP,
            service_type=self.internet,
            branch=self.branch,
            free_meters=Decimal("100.00"),
            excess_price_per_meter=Decimal("1.00"),
            valid_from=date(2026, 1, 1),
        )

    def test_exceso_utp_y_drop_se_calcula_sin_que_tecnico_envie_precios(self):
        utp = record_installation_material_usage(
            work_order=self.order,
            material=InstallationMaterialRule.Material.UTP,
            meters_used=42,
            on_date=date(2026, 9, 4),
        )
        drop = record_installation_material_usage(
            work_order=self.order,
            material=InstallationMaterialRule.Material.DROP,
            meters_used=127,
            on_date=date(2026, 9, 4),
        )
        self.assertEqual(utp.excess_meters, Decimal("12.00"))
        self.assertEqual(utp.excess_charge, Decimal("24.00"))
        self.assertEqual(drop.excess_meters, Decimal("27.00"))
        self.assertEqual(drop.excess_charge, Decimal("27.00"))
        self.assertEqual(total_installation_excess_charge(self.order), Decimal("51.00"))
