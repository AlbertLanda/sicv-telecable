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

    def test_atc_can_consult_customer_billing_information(self):
        self.assertTrue(self.user.has_perm("payments.view_charge"))
        self.assertTrue(self.user.has_perm("payments.view_payment"))
        self.assertTrue(self.user.has_perm("payments.view_receipt"))

    def test_atc_can_register_payment_but_not_administer_billing(self):
        self.assertTrue(self.user.has_perm("payments.add_payment"))
        self.assertFalse(self.user.has_perm("payments.add_charge"))
        self.assertFalse(self.user.has_perm("payments.void_payment"))
        self.assertFalse(
            self.user.has_perm("payments.grant_paymentcommitment")
        )

    def test_atc_cannot_manage_personnel(self):
        self.assertFalse(self.user.has_perm("accounts.view_user"))
        self.assertFalse(self.user.has_perm("accounts.add_user"))
        self.assertFalse(self.user.has_perm("accounts.change_user"))

    def test_inactive_atc_does_not_inherit_role_capabilities(self):
        self.user.is_active = False

        self.assertFalse(self.user.has_perm("customers.add_customer"))
        self.assertFalse(self.user.has_perm("work_orders.schedule_workorder"))
        self.assertFalse(self.user.has_perm("payments.view_payment"))
        self.assertFalse(self.user.has_perm("payments.add_payment"))


class PersonnelManagerRoleBaselinePermissionTests(TestCase):
    def test_admin_role_can_manage_personnel_without_being_superuser(self):
        user = User.objects.create_user(
            username="admin_role_test",
            role=User.Role.ADMIN,
            is_active=True,
        )

        self.assertTrue(user.has_perm("accounts.view_user"))
        self.assertTrue(user.has_perm("accounts.add_user"))
        self.assertTrue(user.has_perm("accounts.change_user"))
        self.assertFalse(user.has_perm("accounts.delete_user"))

    def test_accounting_does_not_inherit_personnel_management(self):
        user = User.objects.create_user(
            username="accounting_test",
            role=User.Role.ACCOUNTING,
            is_active=True,
        )

        self.assertFalse(user.has_perm("accounts.view_user"))
        self.assertFalse(user.has_perm("accounts.add_user"))
        self.assertFalse(user.has_perm("accounts.change_user"))
        self.assertFalse(user.has_perm("accounts.delete_user"))
