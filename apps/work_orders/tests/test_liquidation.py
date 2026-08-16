"""
Pruebas de la liquidación técnica de órdenes (fase 3).

Cubren el servicio liquidate_order(), la transición ATTENDED -> LIQUIDATED,
los materiales/equipos declarados y las evidencias de la atención.

Liquidar documenta la atención: no valida (NOC ni almacén), no cierra la
orden y no mueve inventario. Estas pruebas verifican también esa separación.
"""

import shutil
import tempfile
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.work_orders.models import (
    WorkOrder,
    WorkOrderEvidence,
    WorkOrderLiquidation,
    WorkOrderLiquidationItem,
    WorkOrderStatusHistory,
)
from apps.work_orders.services import liquidate_order
from apps.work_orders.tests.base import WorkOrderTestCase


class WorkOrderLiquidationTests(WorkOrderTestCase):
    """Servicio liquidate_order() y transición ATTENDED -> LIQUIDATED."""

    def test_liquidation_is_created_for_attended_order(self):
        """1. Se crea una liquidación válida para una orden ATTENDED."""
        order = self.create_attended_order()

        liquidation = liquidate_order(
            order,
            user=self.technician,
            resolution_detail="Se instaló ONU y se dejó el servicio operativo.",
            technical_notes="Señal estable en el punto del cliente.",
        )

        self.assertIsInstance(liquidation, WorkOrderLiquidation)
        self.assertEqual(liquidation.work_order, order)
        self.assertEqual(WorkOrderLiquidation.objects.count(), 1)
        self.assertEqual(
            liquidation.resolution_detail,
            "Se instaló ONU y se dejó el servicio operativo.",
        )
        self.assertEqual(
            liquidation.technical_notes,
            "Señal estable en el punto del cliente.",
        )

    def test_attended_to_liquidated_is_allowed(self):
        """2. ATTENDED -> LIQUIDATED se permite."""
        order = self.create_attended_order()

        self.assertTrue(order.can_transition_to(WorkOrder.Status.LIQUIDATED))

        liquidate_order(
            order,
            user=self.technician,
            resolution_detail="Trabajo ejecutado conforme.",
        )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.LIQUIDATED)

    def test_pending_order_cannot_be_liquidated(self):
        """3. Liquidar desde PENDING se rechaza."""
        order = self.create_order()

        with self.assertRaises(ValidationError):
            liquidate_order(
                order,
                user=self.technician,
                resolution_detail="Intento indebido.",
            )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual(WorkOrderLiquidation.objects.count(), 0)

    def test_assigned_order_cannot_be_liquidated(self):
        """4. Liquidar desde ASSIGNED se rechaza."""
        order = self.create_assigned_order()

        with self.assertRaises(ValidationError):
            liquidate_order(
                order,
                user=self.technician,
                resolution_detail="Intento indebido.",
            )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(WorkOrderLiquidation.objects.count(), 0)

    def test_in_progress_order_cannot_be_liquidated(self):
        """5. Liquidar desde IN_PROGRESS se rechaza."""
        order = self.create_order_in_progress()

        with self.assertRaises(ValidationError):
            liquidate_order(
                order,
                user=self.technician,
                resolution_detail="Todavía en atención.",
            )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)
        self.assertEqual(WorkOrderLiquidation.objects.count(), 0)

    def test_order_cannot_be_liquidated_twice(self):
        """6. Una orden ya liquidada no puede liquidarse nuevamente."""
        order = self.create_attended_order()

        liquidate_order(
            order,
            user=self.technician,
            resolution_detail="Primera liquidación.",
        )

        with self.assertRaises(ValidationError):
            liquidate_order(
                order,
                user=self.supervisor,
                resolution_detail="Segunda liquidación.",
            )

        self.assertEqual(WorkOrderLiquidation.objects.count(), 1)
        self.assertEqual(
            WorkOrderLiquidation.objects.get(work_order=order).resolution_detail,
            "Primera liquidación.",
        )

    def test_liquidation_records_liquidated_by(self):
        """7. La liquidación registra el usuario responsable."""
        order = self.create_attended_order()

        liquidation = liquidate_order(
            order,
            user=self.technician,
            resolution_detail="Instalación culminada.",
        )

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.liquidated_by, self.technician)

    def test_liquidation_records_liquidated_at(self):
        """8. La liquidación registra su fecha y hora real."""
        order = self.create_attended_order()

        liquidation = liquidate_order(
            order,
            user=self.technician,
            resolution_detail="Instalación culminada.",
        )

        liquidation.refresh_from_db()

        self.assertIsNotNone(liquidation.liquidated_at)
        # La liquidación es posterior al cierre de la atención.
        self.assertGreaterEqual(liquidation.liquidated_at, order.attended_at)

    def test_liquidation_creates_status_history(self):
        """9. El cambio a LIQUIDATED deja trazabilidad."""
        order = self.create_attended_order()

        liquidate_order(
            order,
            user=self.supervisor,
            resolution_detail="Conforme.",
            remarks="Liquidación revisada en oficina.",
        )

        record = WorkOrderStatusHistory.objects.get(
            work_order=order,
            new_status=WorkOrder.Status.LIQUIDATED,
        )

        self.assertEqual(record.previous_status, WorkOrder.Status.ATTENDED)
        self.assertEqual(record.changed_by, self.supervisor)
        self.assertEqual(record.remarks, "Liquidación revisada en oficina.")

    def test_failed_liquidation_leaves_no_partial_record(self):
        """10. Un error no deja una liquidación parcial."""
        order = self.create_attended_order()

        # El segundo ítem es inválido: debe abortar toda la operación.
        with self.assertRaises(ValidationError):
            liquidate_order(
                order,
                user=self.technician,
                resolution_detail="Instalación con materiales.",
                items=[
                    {
                        "movement_type": (
                            WorkOrderLiquidationItem.MovementType.USED
                        ),
                        "material_name": "Cable drop",
                        "quantity": Decimal("50.00"),
                    },
                    {
                        "movement_type": (
                            WorkOrderLiquidationItem.MovementType.USED
                        ),
                        "material_name": "Conector SC/APC",
                        "quantity": Decimal("0.00"),
                    },
                ],
            )

        order.refresh_from_db()

        self.assertEqual(WorkOrderLiquidation.objects.count(), 0)
        self.assertEqual(WorkOrderLiquidationItem.objects.count(), 0)
        self.assertEqual(order.status, WorkOrder.Status.ATTENDED)
        self.assertFalse(
            WorkOrderStatusHistory.objects.filter(
                work_order=order,
                new_status=WorkOrder.Status.LIQUIDATED,
            ).exists()
        )

    def test_inactive_user_cannot_liquidate(self):
        """14. Un usuario inactivo no puede liquidar."""
        order = self.create_attended_order()

        with self.assertRaises(ValidationError):
            liquidate_order(
                order,
                user=self.inactive_technician,
                resolution_detail="Liquidación de usuario dado de baja.",
            )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.ATTENDED)
        self.assertEqual(WorkOrderLiquidation.objects.count(), 0)

    def test_liquidation_requires_responsible_user(self):
        """Complemento: sin usuario responsable no hay liquidación."""
        order = self.create_attended_order()

        with self.assertRaises(ValidationError):
            liquidate_order(
                order,
                user=None,
                resolution_detail="Sin responsable.",
            )

        self.assertEqual(WorkOrderLiquidation.objects.count(), 0)

    def test_liquidation_requires_resolution_detail(self):
        """Complemento: los datos obligatorios deben estar completos."""
        order = self.create_attended_order()

        with self.assertRaises(ValidationError):
            liquidate_order(
                order,
                user=self.technician,
                resolution_detail="   ",
            )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.ATTENDED)
        self.assertEqual(WorkOrderLiquidation.objects.count(), 0)

    def test_liquidation_stores_technical_field_data(self):
        """Complemento: los datos de red se guardan en campos separados."""
        order = self.create_attended_order()

        liquidation = liquidate_order(
            order,
            user=self.technician,
            resolution_detail="Instalación con tendido nuevo.",
            network_element="NAP-045",
            network_port="3",
            equipment_serial="ZTEG1234ABCD",
            signal_level_dbm=Decimal("-21.40"),
            cable_meters_used=Decimal("85.00"),
        )

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.network_element, "NAP-045")
        self.assertEqual(liquidation.network_port, "3")
        self.assertEqual(liquidation.equipment_serial, "ZTEG1234ABCD")
        self.assertEqual(liquidation.signal_level_dbm, Decimal("-21.40"))
        self.assertEqual(liquidation.cable_meters_used, Decimal("85.00"))
        # Krill queda preparado pero no se consume ninguna API en esta fase.
        self.assertEqual(liquidation.krill_reference, "")

    def test_unknown_technical_data_is_rejected(self):
        """Complemento: un campo técnico desconocido no se acepta."""
        order = self.create_attended_order()

        with self.assertRaises(ValidationError):
            liquidate_order(
                order,
                user=self.technician,
                resolution_detail="Instalación.",
                campo_inventado="valor",
            )

        self.assertEqual(WorkOrderLiquidation.objects.count(), 0)

    def test_is_liquidated_reflects_the_liquidation_record(self):
        """Complemento: is_liquidated depende del registro, no del estado."""
        order = self.create_attended_order()

        self.assertFalse(order.is_liquidated)

        liquidate_order(
            order,
            user=self.technician,
            resolution_detail="Conforme.",
        )

        self.assertTrue(order.is_liquidated)


class WorkOrderLiquidationTransitionTests(WorkOrderTestCase):
    """LIQUIDATED como estado posterior a la atención."""

    def _liquidated_order(self):
        order = self.create_attended_order()

        liquidate_order(
            order,
            user=self.technician,
            resolution_detail="Trabajo ejecutado conforme.",
        )

        order.refresh_from_db()

        return order

    def test_invalid_transition_from_liquidated_is_blocked(self):
        """15. Una transición inválida desde LIQUIDATED queda bloqueada."""
        order = self._liquidated_order()

        for target in (
            WorkOrder.Status.IN_PROGRESS,
            WorkOrder.Status.ASSIGNED,
            WorkOrder.Status.REPROGRAMMED,
            WorkOrder.Status.ATTENDED,
            WorkOrder.Status.CANCELLED,
        ):
            with self.subTest(target=target):
                with self.assertRaises(ValidationError):
                    order.change_status(target, user=self.supervisor)

                order.refresh_from_db()

                self.assertEqual(order.status, WorkOrder.Status.LIQUIDATED)

    def test_liquidated_order_is_closed_for_field_operation(self):
        """Complemento: una orden liquidada no vuelve a la operación."""
        order = self._liquidated_order()

        self.assertTrue(order.is_closed)

        with self.assertRaises(ValidationError):
            order.assign_technician(
                technician=self.other_technician,
                assigned_by=self.supervisor,
            )

        with self.assertRaises(ValidationError):
            order.start_attention(user=self.technician)

    def test_liquidation_does_not_close_the_order(self):
        """
        Complemento: liquidar no equivale a validar ni cerrar.

        No existe todavía estado de validación NOC, validación de almacén ni
        cierre definitivo: LIQUIDATED es la última etapa implementada.
        """
        order = self._liquidated_order()

        self.assertNotIn("VALIDATED", WorkOrder.Status.values)
        self.assertNotIn("CLOSED", WorkOrder.Status.values)
        self.assertEqual(
            WorkOrder.ALLOWED_TRANSITIONS[WorkOrder.Status.LIQUIDATED],
            [],
        )


class WorkOrderLiquidationItemTests(WorkOrderTestCase):
    """Materiales y equipos declarados: informativos y trazables."""

    def setUp(self):
        super().setUp()

        self.order = self.create_attended_order()

    def test_multiple_items_can_be_declared(self):
        """11. Se pueden registrar múltiples materiales/equipos."""
        liquidation = liquidate_order(
            self.order,
            user=self.technician,
            resolution_detail="Instalación con materiales de almacén.",
            items=[
                {
                    "movement_type": WorkOrderLiquidationItem.MovementType.USED,
                    "material_name": "Cable drop fibra",
                    "quantity": Decimal("80.00"),
                    "unit_of_measure": (
                        WorkOrderLiquidationItem.UnitOfMeasure.METER
                    ),
                },
                {
                    "movement_type": WorkOrderLiquidationItem.MovementType.USED,
                    "material_name": "ONU ZTE F670L",
                    "quantity": Decimal("1.00"),
                    "unit_of_measure": (
                        WorkOrderLiquidationItem.UnitOfMeasure.UNIT
                    ),
                },
                {
                    "movement_type": (
                        WorkOrderLiquidationItem.MovementType.REMOVED
                    ),
                    "material_name": "ONU averiada Huawei HG8145",
                    "quantity": Decimal("1.00"),
                    "unit_of_measure": (
                        WorkOrderLiquidationItem.UnitOfMeasure.UNIT
                    ),
                },
            ],
        )

        self.assertEqual(liquidation.items.count(), 3)
        self.assertEqual(
            liquidation.items.filter(
                movement_type=WorkOrderLiquidationItem.MovementType.REMOVED
            ).count(),
            1,
        )

    def test_item_keeps_type_quantity_and_remarks(self):
        """12. Un ítem conserva tipo, cantidad y observación."""
        liquidation = liquidate_order(
            self.order,
            user=self.technician,
            resolution_detail="Cambio de equipo averiado.",
            items=[
                {
                    "movement_type": (
                        WorkOrderLiquidationItem.MovementType.REMOVED
                    ),
                    "material_code": "ONU-001",
                    "material_name": "ONU averiada",
                    "quantity": Decimal("2.00"),
                    "unit_of_measure": (
                        WorkOrderLiquidationItem.UnitOfMeasure.UNIT
                    ),
                    "remarks": "Equipos retirados por daño eléctrico.",
                },
            ],
        )

        item = liquidation.items.get()

        self.assertEqual(
            item.movement_type,
            WorkOrderLiquidationItem.MovementType.REMOVED,
        )
        self.assertEqual(item.material_code, "ONU-001")
        self.assertEqual(item.quantity, Decimal("2.00"))
        self.assertEqual(
            item.unit_of_measure,
            WorkOrderLiquidationItem.UnitOfMeasure.UNIT,
        )
        self.assertEqual(item.remarks, "Equipos retirados por daño eléctrico.")

    def test_declared_items_do_not_touch_stock(self):
        """
        Complemento: la declaración es informativa.

        En esta fase no existe ningún modelo de inventario, kardex ni stock
        por técnico que la liquidación pueda mover.
        """
        liquidate_order(
            self.order,
            user=self.technician,
            resolution_detail="Instalación estándar.",
            items=[
                {
                    "movement_type": WorkOrderLiquidationItem.MovementType.USED,
                    "material_name": "Roseta óptica",
                    "quantity": Decimal("1.00"),
                },
            ],
        )

        item = WorkOrderLiquidationItem.objects.get()

        # El ítem solo conoce su liquidación: no referencia almacén ni stock.
        field_names = {
            field.name
            for field in WorkOrderLiquidationItem._meta.get_fields()
        }

        self.assertNotIn("warehouse", field_names)
        self.assertNotIn("stock", field_names)
        self.assertEqual(item.liquidation.work_order, self.order)

    def test_item_quantity_must_be_positive(self):
        """Complemento: una cantidad no positiva se rechaza."""
        with self.assertRaises(ValidationError):
            liquidate_order(
                self.order,
                user=self.technician,
                resolution_detail="Instalación.",
                items=[
                    {
                        "movement_type": (
                            WorkOrderLiquidationItem.MovementType.USED
                        ),
                        "material_name": "Conector",
                        "quantity": Decimal("-3.00"),
                    },
                ],
            )

        self.assertEqual(WorkOrderLiquidationItem.objects.count(), 0)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="sicv-test-media-"))
class WorkOrderEvidenceTests(WorkOrderTestCase):
    """Evidencias de la atención sobre almacenamiento local."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()

        # Las evidencias de prueba no deben sobrevivir a la corrida.
        shutil.rmtree(cls._overridden_settings["MEDIA_ROOT"], ignore_errors=True)

    def _evidence_file(self, name="evidencia.jpg"):
        return SimpleUploadedFile(
            name,
            b"contenido-binario-de-prueba",
            content_type="image/jpeg",
        )

    def test_evidence_is_linked_to_its_order_and_liquidation(self):
        """13. Las evidencias quedan vinculadas a la orden correcta."""
        order = self.create_attended_order()
        other_order = self.create_attended_order()

        liquidation = liquidate_order(
            order,
            user=self.technician,
            resolution_detail="Instalación con evidencia fotográfica.",
        )

        evidence = WorkOrderEvidence.objects.create(
            work_order=order,
            liquidation=liquidation,
            file=self._evidence_file(),
            description="Foto del punto instalado",
            uploaded_by=self.technician,
        )

        evidence.refresh_from_db()

        self.assertEqual(evidence.work_order, order)
        self.assertEqual(evidence.liquidation, liquidation)
        self.assertEqual(evidence.uploaded_by, self.technician)
        self.assertEqual(order.evidences.count(), 1)
        self.assertEqual(liquidation.evidences.count(), 1)
        self.assertEqual(other_order.evidences.count(), 0)

    def test_evidence_from_another_order_is_rejected(self):
        """Complemento: una liquidación ajena no puede respaldar la evidencia."""
        order = self.create_attended_order()
        other_order = self.create_attended_order()

        other_liquidation = liquidate_order(
            other_order,
            user=self.technician,
            resolution_detail="Otra orden.",
        )

        evidence = WorkOrderEvidence(
            work_order=order,
            liquidation=other_liquidation,
            file=self._evidence_file(),
            description="Evidencia cruzada",
            uploaded_by=self.technician,
        )

        with self.assertRaises(ValidationError):
            evidence.full_clean()

    def test_evidence_is_stored_under_the_order_folder(self):
        """Complemento: el archivo se guarda con almacenamiento local."""
        order = self.create_attended_order()

        evidence = WorkOrderEvidence.objects.create(
            work_order=order,
            file=self._evidence_file("antes.jpg"),
            description="Estado inicial",
            uploaded_by=self.technician,
        )

        self.assertIn(
            f"work_orders/{order.order_number}/evidences/",
            evidence.file.name.replace("\\", "/"),
        )
        self.assertTrue(evidence.file.storage.exists(evidence.file.name))
