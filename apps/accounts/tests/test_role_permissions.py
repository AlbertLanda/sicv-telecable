from django.test import TestCase

from apps.accounts.models import User


class ATCRoleBaselinePermissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="atc_test",
            role=User.Role.ATC,
            is_active=True,
        )

    def test_atc_can_register_customers_and_work_orders(self):
        self.assertTrue(self.user.has_perm("customers.add_customer"))
        self.assertTrue(self.user.has_perm("work_orders.add_workorder"))
        self.assertTrue(self.user.has_perm("work_orders.view_workorder"))

    def test_atc_can_schedule_without_manual_assignment_permission(self):
        self.assertTrue(self.user.has_perm("work_orders.schedule_workorder"))
        self.assertFalse(self.user.has_perm("work_orders.assign_workorder"))

    def test_inactive_atc_does_not_inherit_role_capabilities(self):
        self.user.is_active = False

        self.assertFalse(self.user.has_perm("customers.add_customer"))
        self.assertFalse(self.user.has_perm("work_orders.schedule_workorder"))


class WarehouseRoleBaselinePermissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="almacen_test",
            role=User.Role.WAREHOUSE,
            is_active=True,
        )

    def test_warehouse_can_view_material_movements(self):
        self.assertTrue(
            self.user.has_perm("inventory.view_workordermaterialmovement")
        )

    def test_warehouse_does_not_inherit_noc_incident_permissions(self):
        self.assertFalse(self.user.has_perm("work_orders.view_incident"))
        self.assertFalse(self.user.has_perm("work_orders.start_incident"))
        self.assertFalse(self.user.has_perm("work_orders.close_incident"))

    def test_inactive_warehouse_does_not_inherit_material_permission(self):
        self.user.is_active = False

        self.assertFalse(
            self.user.has_perm("inventory.view_workordermaterialmovement")
        )
