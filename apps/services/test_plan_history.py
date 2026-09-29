from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone

from .models import Plan, ServiceType, Subscription, SubscriptionPlanHistory


class SubscriptionPlanHistoryTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            code="JAUJA-HIST",
            name="Jauja historial",
        )
        self.zone = Zone.objects.create(
            branch=self.branch,
            name="JAUJA D historial",
        )
        self.customer = Customer.objects.create(
            code="JA01-AHIST001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="87654321",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Histórico",
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Sucre 890",
            district="Jauja",
        )
        self.internet = ServiceType.objects.create(
            code="INTERNET-HIST",
            name="Internet histórico",
        )
        self.cable = ServiceType.objects.create(
            code="CABLE-HIST",
            name="TV Cable histórico",
        )
        self.old_plan = Plan.objects.create(
            service_type=self.internet,
            code="OLD-20M",
            name="INTERNET DUO 20MG - 2022 OFICIAL",
            monthly_price=Decimal("0.00"),
        )
        self.current_plan = Plan.objects.create(
            service_type=self.cable,
            code="TV-FTTH-50-HIST",
            name="TV CABLE FTTH - 50",
            monthly_price=Decimal("50.00"),
        )
        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.cable,
            plan=self.current_plan,
            status=Subscription.Status.CUT,
            service_number=1,
            billing_cycle=2,
        )

    def test_historial_no_reescribe_el_plan_actual(self):
        history = SubscriptionPlanHistory.objects.create(
            subscription=self.subscription,
            plan=self.old_plan,
            plan_name_snapshot="",
            start_date=date(2018, 10, 2),
            source=SubscriptionPlanHistory.Source.SICAV,
            source_reference="contrato 648",
        )

        self.subscription.refresh_from_db()
        history.refresh_from_db()

        self.assertEqual(self.subscription.plan, self.current_plan)
        self.assertEqual(history.plan, self.old_plan)
        self.assertEqual(
            history.plan_name_snapshot,
            "INTERNET DUO 20MG - 2022 OFICIAL",
        )
        self.assertEqual(history.service_type, self.internet)
        self.assertEqual(
            history.service_name_snapshot,
            "Internet histórico",
        )

    def test_precio_historico_puede_quedar_pendiente_de_validacion(self):
        history = SubscriptionPlanHistory.objects.create(
            subscription=self.subscription,
            plan=self.old_plan,
            plan_name_snapshot="Plan antiguo",
            start_date=date(2018, 10, 2),
            source=SubscriptionPlanHistory.Source.SICAV,
        )

        self.assertIsNone(history.monthly_fee_snapshot)
        self.assertFalse(history.is_validated)

    def test_precio_historico_es_editable_sin_cambiar_catalogo(self):
        history = SubscriptionPlanHistory.objects.create(
            subscription=self.subscription,
            plan=self.old_plan,
            plan_name_snapshot="Plan antiguo",
            start_date=date(2018, 10, 2),
            monthly_fee_snapshot=Decimal("40.00"),
            source=SubscriptionPlanHistory.Source.SICAV,
        )

        history.monthly_fee_snapshot = Decimal("45.00")
        history.validation_notes = "Validado con documentación comercial."
        history.save()

        self.old_plan.refresh_from_db()
        self.subscription.refresh_from_db()

        self.assertEqual(history.monthly_fee_snapshot, Decimal("45.00"))
        self.assertEqual(self.old_plan.monthly_price, Decimal("0.00"))
        self.assertEqual(self.subscription.plan, self.current_plan)

    def test_fin_no_puede_ser_anterior_al_inicio(self):
        history = SubscriptionPlanHistory(
            subscription=self.subscription,
            plan=self.old_plan,
            plan_name_snapshot="Plan antiguo",
            start_date=date(2025, 5, 7),
            end_date=date(2025, 5, 6),
            source=SubscriptionPlanHistory.Source.SICAV,
        )

        with self.assertRaises(ValidationError):
            history.full_clean()
