import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.customers.models import Customer, CustomerAddress
from apps.legacy.models import (
    LegacyChargeSnapshot,
    LegacyContractSnapshot,
    LegacyPaymentAllocationSnapshot,
    LegacyPaymentSnapshot,
    LegacyReceiptSnapshot,
    LegacyRecord,
    LegacyWorkOrderEvidence,
    LegacyWorkOrderMaterial,
    LegacyWorkOrderParticipant,
    LegacyWorkOrderSnapshot,
)
from apps.organization.models import Branch, Zone
from apps.payments.models import Charge, Payment
from apps.work_orders.models import OrderReason, OrderType, WorkOrder

from apps.services.models import (
    Plan,
    ServiceType,
    Subscription,
    SubscriptionPlanHistory,
)


class ImportarAbonadoSicavTests(TestCase):
    def setUp(self):
        # JAUJA ya viene sembrada por organization.0002_seed_sedes_reales.
        # Reutilizarla mantiene el test alineado con una base real/migrada y
        # evita chocar con la restricción UNIQUE de Branch.code.
        self.branch = Branch.objects.get(code="JAUJA")
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
        self.installation_type, _ = OrderType.objects.get_or_create(
            code="INSTALLATION",
            defaults={
                "name": "INSTALACIÓN",
                "description": "Instalación histórica de prueba.",
                "is_active": True,
            },
        )
        self.installation_reason, _ = OrderReason.objects.get_or_create(
            order_type=self.installation_type,
            code="REQUIRED",
            defaults={
                "name": "REQUERIDO",
                "classification": OrderReason.Classification.TECHNICAL,
                "is_active": True,
            },
        )
        self.incident_type, _ = OrderType.objects.get_or_create(
            code="INCIDENT",
            defaults={
                "name": "INCIDENCIA NOC",
                "description": "Incidencia histórica de prueba.",
                "is_active": True,
            },
        )
        self.incident_reason, _ = OrderReason.objects.get_or_create(
            order_type=self.incident_type,
            code="NO_SIGNAL",
            defaults={
                "name": "SIN SEÑAL",
                "classification": OrderReason.Classification.TECHNICAL,
                "is_active": True,
            },
        )
        self.fault_type, _ = OrderType.objects.get_or_create(
            code="INTERNET_FAULT",
            defaults={
                "name": "AVERÍA INTERNET",
                "description": "Avería histórica de prueba.",
                "is_active": True,
            },
        )
        self.fault_reason, _ = OrderReason.objects.get_or_create(
            order_type=self.fault_type,
            code="HIGH_POWER",
            defaults={
                "name": "POTENCIA ELEVADA",
                "classification": OrderReason.Classification.TECHNICAL,
                "is_active": True,
            },
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
            "contracts": [
                {
                    "legacy_id": "648-TEST",
                    "raw": {
                        "codigo": "648-TEST",
                        "numero": "0000335",
                        "servicio": "INTERNET",
                        "plan": "INTERNET 20MG - 2022 OFICIAL",
                        "estado": "U",
                        "modalidad": "V",
                        "inicio": "02/10/2018",
                        "fin": "01/01/1900",
                    },
                    "normalized": {
                        "subscription_legacy_id": "523-TEST",
                        "contract_number": "0000335",
                        "service_type_code": "INTERNET",
                        "plan_code": "SICAV-016",
                        "service_name_snapshot": "INTERNET",
                        "plan_name_snapshot": "INTERNET 20MG - 2022 OFICIAL",
                        "status": "U",
                        "legacy_status": "Anulado",
                        "modality": "V",
                        "installments": 1,
                        "start_date": "02/10/2018",
                        "end_date": "01/01/1900",
                        "last_activation_date": "01/01/1900",
                        "last_cut_date": "01/01/1900",
                        "is_validated": False,
                    },
                }
            ],
            "work_orders": [
                {
                    "legacy_id": "102352-TEST",
                    "raw": {
                        "codigo": "102352-TEST",
                        "tipo": "NI",
                        "estado": "D",
                        "emision": "27/04/2025 11:21",
                    },
                    "normalized": {
                        "subscription_legacy_id": "523-TEST",
                        "order_number": "0013181",
                        "order_type_code": "INCIDENT",
                        "order_type_name_snapshot": "INCIDENCIA NOC",
                        "reason_code": "NO_SIGNAL",
                        "reason_name_snapshot": "SIN SEÑAL",
                        "legacy_type_code": "NI",
                        "status": "D",
                        "legacy_status": "Derivado",
                        "attention_type": "SISTEMA",
                        "responsibility": "EMPRESA",
                        "detail": "SIN SEÑAL DE INTERNET",
                        "attention_detail": "POTENCIA ATENUADA",
                        "issued_at": "27/04/2025 11:21",
                        "attended_at": "27/04/2025 11:26",
                        "terminal": "11",
                        "seal_number": "2285607",
                        "participants": [
                            {
                                "legacy_user_code": "0000014",
                                "name_snapshot": "NOC",
                                "role_snapshot": "NOC",
                                "started_at": "27/04/2025 11:21",
                                "ended_at": "27/04/2025 11:26"
                            }
                        ],
                        "materials": [
                            {
                                "legacy_material_code": "EMPTY",
                                "name_snapshot": "MATERIAL NO USADO",
                                "quantity": "0"
                            }
                        ],
                        "evidences": []
                    },
                },
                {
                    "legacy_id": "102353-TEST",
                    "raw": {
                        "codigo": "102353-TEST",
                        "estado": "A",
                        "emision": "27/04/2025 11:26",
                    },
                    "normalized": {
                        "subscription_legacy_id": "523-TEST",
                        "order_number": "0000523",
                        "order_type_code": "INTERNET_FAULT",
                        "order_type_name_snapshot": "AVERÍA",
                        "reason_code": "HIGH_POWER",
                        "reason_name_snapshot": "POTENCIA ELEVADA",
                        "status": "A",
                        "legacy_status": "Atendido",
                        "attention_type": "F",
                        "responsibility": "EMPRESA",
                        "detail": "POTENCIA FUERA DE RANGO",
                        "attention_detail": "POTENCIA ESTABLE",
                        "technical_notes": "Prueba histórica.",
                        "issued_at": "27/04/2025 11:26",
                        "attended_at": "28/04/2025 11:50",
                        "terminal": "11",
                        "seal_number": "2285607",
                        "derived_from_legacy_id": "102352-TEST",
                        "participants": [
                            {
                                "legacy_user_code": "0000042",
                                "name_snapshot": "Técnico histórico",
                                "role_snapshot": "Técnico",
                                "started_at": "28/04/2025 11:00",
                                "ended_at": "28/04/2025 11:50"
                            }
                        ],
                        "materials": [
                            {
                                "legacy_material_code": "CM-TEST",
                                "name_snapshot": "CONECTOR MECÁNICO",
                                "quantity": "1.00000",
                                "unit_snapshot": "Unidad",
                                "movement_type": "USED"
                            }
                        ],
                        "evidences": [
                            {
                                "original_name": "evidencia-prueba.jpg",
                                "legacy_reference": "/galeria/ver/modulo/ordenTecnica/codigo/102353-TEST/nombre/evidencia-prueba.jpg",
                                "description": "Evidencia histórica de prueba"
                            }
                        ]
                    },
                }
            ],
        }

    def expediente_financiero(self):
        payload = self.expediente()
        payload["charges_history"] = [
            {
                "legacy_id": "1037678-TEST",
                "raw": {
                    "id": "1037678-TEST",
                    "detalle": "TV CABLE FTTH",
                    "monto": "38.70",
                    "documento": "S-TEST",
                },
                "normalized": {
                    "subscription_legacy_id": "523-TEST",
                    "description": "TV CABLE FTTH",
                    "quantity": "1.00000",
                    "currency": "PEN",
                    "period_start": "01/05/2025",
                    "period_end": "31/05/2025",
                    "amount": "38.70",
                    "due_date": "31/05/2025",
                    "legacy_date": "05/06/2025",
                    "document_snapshot": "S-TEST",
                    "status": "PAID",
                },
            },
            {
                "legacy_id": "1037679-TEST",
                "raw": {
                    "id": "1037679-TEST",
                    "detalle": "DUO RESIDENCIAL 300MG",
                    "monto": "13.70",
                    "documento": "S-TEST",
                },
                "normalized": {
                    "subscription_legacy_id": "523-TEST",
                    "description": "DUO RESIDENCIAL 300MG",
                    "quantity": "1.00000",
                    "currency": "PEN",
                    "period_start": "01/05/2025",
                    "period_end": "31/05/2025",
                    "amount": "13.70",
                    "due_date": "31/05/2025",
                    "legacy_date": "05/06/2025",
                    "document_snapshot": "S-TEST",
                    "status": "PAID",
                },
            },
        ]
        payload["payments"] = [
            {
                "legacy_id": "0524102-TEST",
                "raw": {
                    "codigo": "0524102-TEST",
                    "total": "52.40",
                    "medio": "005",
                },
                "normalized": {
                    "branch_code": "JAUJA",
                    "amount": "52.40",
                    "currency": "PEN",
                    "method_code": "005",
                    "method_snapshot": "YAPE",
                    "reference": "OPERACION-PRUEBA",
                    "status": "REGISTERED",
                    "issued_at": "05/06/2025 21:06",
                    "paid_at": "05/06/2025 21:06",
                    "registered_at": "05/06/2025 21:07",
                    "collector_snapshot": "COBRADOR PRUEBA",
                    "registered_by_snapshot": "USUARIO PRUEBA",
                },
            }
        ]
        payload["payment_allocations"] = [
            {
                "legacy_id": "0524102-TEST:1037678-TEST",
                "raw": {
                    "pago": "0524102-TEST",
                    "deuda": "1037678-TEST",
                    "monto": "38.70",
                },
                "normalized": {
                    "payment_legacy_id": "0524102-TEST",
                    "charge_legacy_id": "1037678-TEST",
                    "amount": "38.70",
                    "discount": "0.00",
                },
            },
            {
                "legacy_id": "0524102-TEST:1037679-TEST",
                "raw": {
                    "pago": "0524102-TEST",
                    "deuda": "1037679-TEST",
                    "monto": "13.70",
                },
                "normalized": {
                    "payment_legacy_id": "0524102-TEST",
                    "charge_legacy_id": "1037679-TEST",
                    "amount": "13.70",
                    "discount": "0.00",
                },
            },
        ]
        payload["receipts"] = [
            {
                "legacy_id": "RECEIPT-0524102-TEST",
                "raw": {
                    "pago": "0524102-TEST",
                    "documento": "S001-0000001",
                },
                "normalized": {
                    "payment_legacy_id": "0524102-TEST",
                    "document_snapshot": "S001-0000001",
                    "series": "S001",
                    "number": "0000001",
                    "document_type_snapshot": "RECIBO",
                    "total": "52.40",
                    "issued_at": "05/06/2025 21:06",
                    "legacy_pdf_reference": "/cobrar/ver/descargar/0524102-TEST/tipo/pdf",
                    "legacy_xml_reference": "/cobrar/ver/descargar/0524102-TEST/tipo/xml",
                },
            }
        ]
        payload["outstanding_charges"] = [
            {
                "legacy_id": "1073773-TEST",
                "raw": {
                    "id": "1073773-TEST",
                    "detalle": "TV CABLE FTTH",
                    "periodo": "01/09/2025 - 30/09/2025",
                    "monto": "50.00",
                },
                "normalized": {
                    "subscription_legacy_id": "523-TEST",
                    "concept": "MONTHLY",
                    "description": "TV CABLE FTTH",
                    "issued_on": "01/09/2025",
                    "quantity": "1.00000",
                    "currency": "PEN",
                    "period_start": "01/09/2025",
                    "period_end": "30/09/2025",
                    "amount": "50.00",
                    "due_date": "30/09/2025",
                },
            },
            {
                "legacy_id": "1254777-TEST",
                "raw": {
                    "id": "1254777-TEST",
                    "detalle": "ANEXO FTTH",
                    "periodo": "01/09/2025 - 30/09/2025",
                    "monto": "5.00",
                },
                "normalized": {
                    "subscription_legacy_id": "523-TEST",
                    "concept": "ANNEX",
                    "description": "ANEXO FTTH",
                    "issued_on": "01/09/2025",
                    "quantity": "1.00000",
                    "currency": "PEN",
                    "period_start": "01/09/2025",
                    "period_end": "30/09/2025",
                    "amount": "5.00",
                    "due_date": "30/09/2025",
                },
            },
            {
                "legacy_id": "1091414-TEST",
                "raw": {
                    "id": "1091414-TEST",
                    "detalle": "TV CABLE FTTH",
                    "periodo": "01/10/2025 - 31/10/2025",
                    "monto": "11.30",
                },
                "normalized": {
                    "subscription_legacy_id": "523-TEST",
                    "concept": "MONTHLY",
                    "description": "TV CABLE FTTH",
                    "issued_on": "01/10/2025",
                    "quantity": "1.00000",
                    "currency": "PEN",
                    "period_start": "01/10/2025",
                    "period_end": "31/10/2025",
                    "amount": "11.30",
                    "due_date": "31/10/2025",
                },
            },
            {
                "legacy_id": "1254778-TEST",
                "raw": {
                    "id": "1254778-TEST",
                    "detalle": "ANEXO FTTH",
                    "periodo": "01/10/2025 - 31/10/2025",
                    "monto": "5.00",
                },
                "normalized": {
                    "subscription_legacy_id": "523-TEST",
                    "concept": "ANNEX",
                    "description": "ANEXO FTTH",
                    "issued_on": "01/10/2025",
                    "quantity": "1.00000",
                    "currency": "PEN",
                    "period_start": "01/10/2025",
                    "period_end": "31/10/2025",
                    "amount": "5.00",
                    "due_date": "31/10/2025",
                },
            },
        ]
        payload["reconciliation"] = {
            "contract_count": 1,
            "work_order_count": 2,
            "historical_charge_count": 2,
            "payment_count": 1,
            "payment_allocation_count": 2,
            "receipt_count": 1,
            "outstanding_count": 4,
            "outstanding_total": "71.30",
            "require_full_payment_allocation": True,
        }
        return payload

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
        self.assertFalse(LegacyContractSnapshot.objects.exists())
        self.assertFalse(LegacyWorkOrderSnapshot.objects.exists())
        self.assertFalse(LegacyWorkOrderParticipant.objects.exists())
        self.assertFalse(LegacyWorkOrderMaterial.objects.exists())
        self.assertFalse(LegacyWorkOrderEvidence.objects.exists())
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
        contract = LegacyContractSnapshot.objects.get(
            subscription=subscription
        )
        incident = LegacyWorkOrderSnapshot.objects.get(
            legacy_order_number="0013181"
        )
        fault = LegacyWorkOrderSnapshot.objects.get(
            legacy_order_number="0000523"
        )

        self.assertEqual(contract.plan, self.old_plan)
        self.assertEqual(
            contract.status,
            LegacyContractSnapshot.Status.CANCELLED,
        )
        self.assertIsNone(contract.end_date)
        self.assertEqual(fault.derived_from, incident)
        self.assertEqual(
            fault.attention_type,
            LegacyWorkOrderSnapshot.AttentionType.FIELD,
        )
        self.assertEqual(
            fault.responsibility,
            LegacyWorkOrderSnapshot.Responsibility.COMPANY,
        )
        self.assertEqual(fault.materials.count(), 1)
        self.assertEqual(fault.participants.count(), 1)
        self.assertEqual(fault.evidences.count(), 1)
        self.assertEqual(incident.materials.count(), 0)
        self.assertEqual(
            WorkOrder.objects.count(),
            0,
            "Las OT históricas no deben publicarse al flujo operativo.",
        )

        self.assertEqual(
            LegacyRecord.objects.filter(
                source=LegacyRecord.Source.SICAV
            ).count(),
            7,
        )

    def test_repetir_el_mismo_expediente_no_duplica(self):
        path = self.write_file(self.expediente())

        call_command("importar_abonado_sicav", archivo=str(path), verbosity=0)
        call_command("importar_abonado_sicav", archivo=str(path), verbosity=0)

        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(CustomerAddress.objects.count(), 1)
        self.assertEqual(Subscription.objects.count(), 1)
        self.assertEqual(SubscriptionPlanHistory.objects.count(), 1)
        self.assertEqual(LegacyContractSnapshot.objects.count(), 1)
        self.assertEqual(LegacyWorkOrderSnapshot.objects.count(), 2)
        self.assertEqual(LegacyWorkOrderParticipant.objects.count(), 2)
        self.assertEqual(LegacyWorkOrderMaterial.objects.count(), 1)
        self.assertEqual(LegacyWorkOrderEvidence.objects.count(), 1)
        self.assertEqual(LegacyRecord.objects.count(), 7)

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


    def test_evidencia_rechaza_token_de_sesion(self):
        payload = self.expediente()
        payload["work_orders"][1]["normalized"]["evidences"][0][
            "legacy_reference"
        ] = "/galeria/ver?id=1&token=secreto"
        path = self.write_file(payload)

        with self.assertRaises(CommandError):
            call_command(
                "importar_abonado_sicav",
                archivo=str(path),
                verbosity=0,
            )

        self.assertFalse(Customer.objects.exists())
        self.assertFalse(LegacyWorkOrderSnapshot.objects.exists())


    def test_no_infiere_derivacion_solo_por_fechas(self):
        payload = self.expediente()
        del payload["work_orders"][1]["normalized"]["derived_from_legacy_id"]
        path = self.write_file(payload)

        call_command(
            "importar_abonado_sicav",
            archivo=str(path),
            verbosity=0,
        )

        fault = LegacyWorkOrderSnapshot.objects.get(
            legacy_order_number="0000523"
        )
        self.assertIsNone(fault.derived_from)


    def test_finanzas_historicas_y_deuda_viva_se_separan(self):
        path = self.write_file(self.expediente_financiero())

        call_command(
            "importar_abonado_sicav",
            archivo=str(path),
            verbosity=0,
        )

        self.assertEqual(LegacyChargeSnapshot.objects.count(), 2)
        self.assertEqual(LegacyPaymentSnapshot.objects.count(), 1)
        self.assertEqual(LegacyPaymentAllocationSnapshot.objects.count(), 2)
        self.assertEqual(LegacyReceiptSnapshot.objects.count(), 1)

        payment = LegacyPaymentSnapshot.objects.get()
        allocated = sum(
            (item.amount for item in payment.allocations.all()),
            0,
        )
        self.assertEqual(str(payment.amount), "52.40")
        self.assertEqual(str(allocated), "52.40")

        self.assertEqual(
            Payment.objects.count(),
            0,
            "Los pagos antiguos no deben entrar a la caja operativa.",
        )

        charges = Charge.objects.order_by("period", "concept")
        self.assertEqual(charges.count(), 4)
        self.assertTrue(all(not charge.auto_update for charge in charges))
        self.assertTrue(
            all(charge.status == Charge.Status.PENDING for charge in charges)
        )
        total = sum((charge.amount for charge in charges), 0)
        self.assertEqual(str(total), "71.30")

        september = Charge.objects.filter(period="2025-09-01")
        self.assertEqual(september.count(), 2)
        self.assertEqual(
            september.filter(concept=Charge.Concept.MONTHLY).count(),
            1,
        )
        self.assertEqual(
            september.filter(concept=Charge.Concept.ANNEX).count(),
            1,
        )

    def test_reimportar_finanzas_no_duplica(self):
        path = self.write_file(self.expediente_financiero())

        call_command("importar_abonado_sicav", archivo=str(path), verbosity=0)
        call_command("importar_abonado_sicav", archivo=str(path), verbosity=0)

        self.assertEqual(LegacyChargeSnapshot.objects.count(), 2)
        self.assertEqual(LegacyPaymentSnapshot.objects.count(), 1)
        self.assertEqual(LegacyPaymentAllocationSnapshot.objects.count(), 2)
        self.assertEqual(LegacyReceiptSnapshot.objects.count(), 1)
        self.assertEqual(Charge.objects.count(), 4)

    def test_conciliacion_deuda_incorrecta_revierte_todo(self):
        payload = self.expediente_financiero()
        payload["reconciliation"]["outstanding_total"] = "70.00"
        path = self.write_file(payload)

        with self.assertRaises(CommandError):
            call_command(
                "importar_abonado_sicav",
                archivo=str(path),
                verbosity=0,
            )

        self.assertFalse(Customer.objects.exists())
        self.assertFalse(Charge.objects.exists())
        self.assertFalse(LegacyPaymentSnapshot.objects.exists())

    def test_finanzas_dry_run_no_persisten(self):
        path = self.write_file(self.expediente_financiero())

        call_command(
            "importar_abonado_sicav",
            archivo=str(path),
            dry_run=True,
            verbosity=0,
        )

        self.assertFalse(Customer.objects.exists())
        self.assertFalse(Charge.objects.exists())
        self.assertFalse(LegacyChargeSnapshot.objects.exists())
        self.assertFalse(LegacyPaymentSnapshot.objects.exists())
        self.assertFalse(LegacyReceiptSnapshot.objects.exists())

    def test_referencia_financiera_rechaza_token(self):
        payload = self.expediente_financiero()
        payload["receipts"][0]["normalized"][
            "legacy_xml_reference"
        ] = "/cobrar/xml?token=secreto"
        path = self.write_file(payload)

        with self.assertRaises(CommandError):
            call_command(
                "importar_abonado_sicav",
                archivo=str(path),
                verbosity=0,
            )

        self.assertFalse(Customer.objects.exists())
        self.assertFalse(Charge.objects.exists())
