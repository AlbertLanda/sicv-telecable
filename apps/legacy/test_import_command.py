import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.customers.models import Customer, CustomerAddress
from apps.legacy.models import LegacyRecord
from apps.organization.models import Branch, Zone
from apps.services.models import (
    Plan,
    ServiceType,
    Subscription,
    SubscriptionPlanHistory,
)


class ImportarAbonadoSicavTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="JAUJA", name="Jauja")
        self.zone = Zone.objects.create(
            branch=self.branch,
            name="JAUJA D",
        )
        self.internet = ServiceType.objects.create(
            code="INTERNET",
            name="INTERNET",
        )
        self.cable = ServiceType.objects.create(
            code="CABLE",
            name="TV CABLE",
            supports_tv_annexes=True,
        )
        self.old_plan = Plan.objects.create(
            service_type=self.internet,
            code="SICAV-016",
            name="INTERNET 20MG - 2022 OFICIAL",
            monthly_price=0,
        )
        self.current_plan = Plan.objects.create(
            service_type=self.cable,
            code="TVC-FTTH-50",
            name="TV CABLE FTTH - 50",
            technology="FTTH",
            monthly_price=0,
        )
        self.tempdir = TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

    def expediente(self):
        return {
            "schema_version": 1,
            "source": "SICAV",
            "customer": {
                "legacy_id": "CLI-LEGACY-001",
                "raw": {
                    "codigo": "CLI-LEGACY-001",
                    "documento": "00000001",
                    "estado": "C",
                },
                "normalized": {
                    "code": "JA01-A9999991",
                    "branch_code": "JAUJA",
                    "document_type": "DNI",
                    "document_number": "00000001",
                    "person_type": "NATURAL",
                    "first_name": "Cliente",
                    "paternal_surname": "Piloto",
                    "phone": "900000001",
                    "is_active": True,
                },
            },
            "addresses": [
                {
                    "legacy_id": "CLI-LEGACY-001:PRIMARY",
                    "raw": {
                        "direccion": "JR. PRUEBA 100",
                        "zona": "JAUJA D",
                    },
                    "normalized": {
                        "address": "JR. PRUEBA 100",
                        "reference": "REFERENCIA DE PRUEBA",
                        "district": "Jauja",
                        "zone_name": "JAUJA D",
                        "is_primary": True,
                        "is_active": True,
                    },
                }
            ],
            "subscriptions": [
                {
                    "legacy_id": "523-TEST",
                    "raw": {
                        "codigo": "523-TEST",
                        "plan_id": "198",
                        "estado": "C",
                        "fechaInicio": "02/10/2018",
                        "fechaFin": "01/01/1900",
                    },
                    "normalized": {
                        "address_legacy_id": "CLI-LEGACY-001:PRIMARY",
                        "service_type_code": "CABLE",
                        "plan_code": "TVC-FTTH-50",
                        "status": "C",
                        "service_number": 1,
                        "billing_cycle": 2,
                        "base_monthly_fee": "50.00",
                        "annex_count": 1,
                        "installation_date": "03/10/2018",
                        "cut_date": "08/10/2025",
                        "reconnection_date": "07/05/2025",
                        "is_active": True,
                    },
                }
            ],
            "plan_history": [
                {
                    "legacy_id": "CONTRACT-648-TEST",
                    "raw": {
                        "contrato": "648-TEST",
                        "plan": "INTERNET 20MG - 2022 OFICIAL",
                        "inicio": "02/10/2018",
                        "fin": "01/01/1900",
                    },
                    "normalized": {
                        "subscription_legacy_id": "523-TEST",
                        "service_type_code": "INTERNET",
                        "plan_code": "SICAV-016",
                        "plan_name_snapshot": "INTERNET 20MG - 2022 OFICIAL",
                        "start_date": "02/10/2018",
                        "end_date": "01/01/1900",
                        "monthly_fee_snapshot": None,
                        "source_reference": "contrato 648-TEST",
                        "is_validated": False,
                    },
                }
            ],
        }

    def write_file(self, payload):
        path = Path(self.tempdir.name) / "expediente.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_dry_run_valida_todo_y_revierte(self):
        path = self.write_file(self.expediente())

        call_command(
            "importar_abonado_sicav",
            archivo=str(path),
            dry_run=True,
            verbosity=0,
        )

        self.assertFalse(Customer.objects.exists())
        self.assertFalse(CustomerAddress.objects.exists())
        self.assertFalse(Subscription.objects.exists())
        self.assertFalse(SubscriptionPlanHistory.objects.exists())
        self.assertFalse(LegacyRecord.objects.exists())

    def test_importa_bloque_maestro_y_normaliza_fecha_1900(self):
        path = self.write_file(self.expediente())

        call_command(
            "importar_abonado_sicav",
            archivo=str(path),
            verbosity=0,
        )

        customer = Customer.objects.get(code="JA01-A9999991")
        address = CustomerAddress.objects.get(customer=customer)
        subscription = Subscription.objects.get(customer=customer)
        history = SubscriptionPlanHistory.objects.get(
            subscription=subscription
        )

        self.assertEqual(address.zone, self.zone)
        self.assertEqual(subscription.status, Subscription.Status.CUT)
        self.assertEqual(subscription.billing_cycle, 2)
        self.assertEqual(str(subscription.base_monthly_fee), "50.00")
        self.assertEqual(subscription.annex_count, 1)
        self.assertIsNone(history.end_date)
        self.assertEqual(history.plan, self.old_plan)
        self.assertEqual(
            LegacyRecord.objects.filter(
                source=LegacyRecord.Source.SICAV
            ).count(),
            4,
        )

    def test_repetir_el_mismo_expediente_no_duplica(self):
        path = self.write_file(self.expediente())

        call_command("importar_abonado_sicav", archivo=str(path), verbosity=0)
        call_command("importar_abonado_sicav", archivo=str(path), verbosity=0)

        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(CustomerAddress.objects.count(), 1)
        self.assertEqual(Subscription.objects.count(), 1)
        self.assertEqual(SubscriptionPlanHistory.objects.count(), 1)
        self.assertEqual(LegacyRecord.objects.count(), 4)

    def test_payload_original_distinto_bloquea_reimportacion(self):
        payload = self.expediente()
        path = self.write_file(payload)
        call_command("importar_abonado_sicav", archivo=str(path), verbosity=0)

        payload["subscriptions"][0]["raw"]["estado"] = "A"
        path = self.write_file(payload)

        with self.assertRaises(CommandError):
            call_command(
                "importar_abonado_sicav",
                archivo=str(path),
                verbosity=0,
            )

        subscription = Subscription.objects.get()
        self.assertEqual(subscription.status, Subscription.Status.CUT)

    def test_zona_desconocida_no_se_inventa(self):
        payload = self.expediente()
        payload["addresses"][0]["normalized"]["zone_name"] = "ZONA NO VALIDADA"
        path = self.write_file(payload)

        call_command("importar_abonado_sicav", archivo=str(path), verbosity=0)

        address = CustomerAddress.objects.get()
        self.assertIsNone(address.zone)
        record = LegacyRecord.objects.get(
            entity_type=LegacyRecord.EntityType.ADDRESS
        )
        self.assertEqual(
            record.normalized_payload["zone_name"],
            "ZONA NO VALIDADA",
        )
