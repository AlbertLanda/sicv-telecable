"""Sincronización entre materiales instalados y metraje/exceso de instalación."""

from decimal import Decimal

from apps.inventory.models import Material, WorkOrderMaterialMovement
from apps.inventory.services import (
    delete_work_order_material,
    record_work_order_material,
)
from apps.services.models import InstallationMaterialRule, InstallationMaterialUsage
from apps.work_orders.tests.base import WorkOrderTestCase


class InstalledCableExcessSyncTests(WorkOrderTestCase):
    def setUp(self):
        super().setUp()
        self.order = self.create_order_in_progress()
        self.rg6 = Material.objects.get(code="CABLE_RG6")
        self.rule = InstallationMaterialRule.objects.create(
            material=InstallationMaterialRule.Material.RG6,
            service_type=self.service_type,
            branch=self.branch,
            free_meters=Decimal("10.00"),
            excess_price_per_meter=Decimal("2.00"),
        )

    def install_rg6(self, quantity):
        return record_work_order_material(
            work_order=self.order,
            material=self.rg6,
            movement_type=WorkOrderMaterialMovement.MovementType.INSTALLED,
            quantity=Decimal(quantity),
            user=self.technician,
        )

    def test_installed_meter_material_creates_usage_and_excess_automatically(self):
        self.install_rg6("12.00")

        usage = InstallationMaterialUsage.objects.get(work_order=self.order)

        self.assertEqual(usage.rule, self.rule)
        self.assertEqual(usage.meters_used, Decimal("12.00"))
        self.assertEqual(usage.free_meters_snapshot, Decimal("10.00"))
        self.assertEqual(usage.excess_meters, Decimal("2.00"))
        self.assertEqual(usage.excess_charge, Decimal("4.00"))

    def test_correcting_installed_quantity_updates_same_usage(self):
        self.install_rg6("12.00")
        self.install_rg6("15.00")

        usages = InstallationMaterialUsage.objects.filter(work_order=self.order)

        self.assertEqual(usages.count(), 1)
        usage = usages.get()
        self.assertEqual(usage.meters_used, Decimal("15.00"))
        self.assertEqual(usage.excess_meters, Decimal("5.00"))
        self.assertEqual(usage.excess_charge, Decimal("10.00"))

    def test_removed_cable_does_not_change_installed_meter_usage(self):
        self.install_rg6("12.00")

        record_work_order_material(
            work_order=self.order,
            material=self.rg6,
            movement_type=WorkOrderMaterialMovement.MovementType.REMOVED,
            quantity=Decimal("3.00"),
            user=self.technician,
        )

        usage = InstallationMaterialUsage.objects.get(work_order=self.order)
        self.assertEqual(usage.meters_used, Decimal("12.00"))
        self.assertEqual(usage.excess_meters, Decimal("2.00"))

    def test_deleting_installed_cable_removes_automatic_usage(self):
        movement = self.install_rg6("12.00")

        delete_work_order_material(
            work_order=self.order,
            movement=movement,
            user=self.technician,
        )

        self.assertFalse(
            InstallationMaterialUsage.objects.filter(work_order=self.order).exists()
        )

    def test_missing_excess_rule_does_not_block_material_registration(self):
        self.rule.delete()

        movement = self.install_rg6("12.00")

        self.assertTrue(
            WorkOrderMaterialMovement.objects.filter(pk=movement.pk).exists()
        )
        self.assertFalse(
            InstallationMaterialUsage.objects.filter(work_order=self.order).exists()
        )
