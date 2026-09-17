"""Regresiones detectadas al integrar reportes con el flujo técnico actual."""

from datetime import timedelta

from django.utils import timezone

from apps.inventory.models import WorkOrderMaterialMovement
from apps.reports.materials import REPORT_SCOPES
from apps.work_orders.models import OrderType, WorkOrderLiquidation

from .test_api_logistics_materials import (
    IDS,
    LogisticsFeedTestCase,
    WATERMARK,
)


class LogisticsIntegrationHardeningTests(LogisticsFeedTestCase):
    def test_incremental_detects_liquidation_review_change_without_touching_order(self):
        """Un cambio de revisión debe volver a publicar el movimiento.

        La validación administrativa modifica datos que viajan en el feed, pero
        no necesariamente toca WorkOrder.updated_at ni el movimiento de material.
        """
        order = self.make_order(self.make_customer("CLI901"))
        self.add_material(order, self.utp, "12.00")
        self.attend(order, timezone.now())

        liquidation = WorkOrderLiquidation.objects.create(
            work_order=order,
            liquidated_by=self.technician,
            liquidated_at=timezone.now(),
            resolution_detail="Trabajo concluido.",
        )

        watermark = self.get(WATERMARK).data["watermark"]
        self.assertIsNotNone(watermark)
        self.assertEqual(len(self.rows(updated_since=watermark)), 0)

        validated_at = timezone.now() + timedelta(seconds=1)
        WorkOrderLiquidation.objects.filter(pk=liquidation.pk).update(
            review_status=WorkOrderLiquidation.ReviewStatus.VALIDATED,
            validated_by=self.service,
            validated_at=validated_at,
        )

        rows = self.rows(updated_since=watermark)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["liquidation_status"], "VALIDATED")
        self.assertGreater(rows[0]["changed_at"], watermark)

    def test_ids_reconciliation_rejects_updated_since(self):
        """La lista de ids nunca puede ser incremental."""
        order = self.make_order(self.make_customer("CLI902"))
        self.add_material(order, self.utp, "8.00")
        self.attend(order, timezone.now())

        response = self.get(
            IDS,
            updated_since=timezone.now().isoformat(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("updated_since", response.data)

    def test_fault_scopes_separate_internet_and_cable_and_keep_combined_filter(self):
        internet_type = OrderType.objects.create(
            code="INTERNET_FAULT",
            name="AVERÍA INTERNET",
        )
        cable_type = OrderType.objects.create(
            code="CABLE_FAULT",
            name="AVERÍA CABLE",
        )

        internet = self.make_order(
            self.make_customer("CLI903"),
            order_type=internet_type,
        )
        cable = self.make_order(
            self.make_customer("CLI904"),
            order_type=cable_type,
        )

        self.add_material(
            internet,
            self.utp,
            "5.00",
            WorkOrderMaterialMovement.MovementType.INSTALLED,
        )
        self.add_material(
            cable,
            self.utp,
            "7.00",
            WorkOrderMaterialMovement.MovementType.INSTALLED,
        )
        self.attend(internet, timezone.now())
        self.attend(cable, timezone.now())

        internet_rows = self.rows(scope="INTERNET_FAULT")
        cable_rows = self.rows(scope="CABLE_FAULT")
        all_fault_rows = self.rows(scope="FAULT")

        self.assertEqual(len(internet_rows), 1)
        self.assertEqual(internet_rows[0]["order_type_code"], "INTERNET_FAULT")
        self.assertEqual(len(cable_rows), 1)
        self.assertEqual(cable_rows[0]["order_type_code"], "CABLE_FAULT")
        self.assertEqual(len(all_fault_rows), 2)
        self.assertEqual(REPORT_SCOPES["FAULT"]["label"], "Averías - Internet y Cable")
