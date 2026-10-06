import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerAddress
from apps.customers.onboarding import incomplete_registration_issues
from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch
from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.installation_withdrawal import installation_withdrawal_issues
from apps.work_orders.models import OrderType, WorkOrder

from .models import Equipment, EquipmentAssignment, EquipmentReview
from .services import assign_equipment, register_equipment, remove_equipment, review_equipment


class EquipmentFixtures:
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(code="EQ-A", name="Sede equipos A")
        self.other_branch = Branch.objects.create(code="EQ-B", name="Sede equipos B")
        self.admin = User.objects.create_user(username="eq-admin", role=User.Role.ADMIN, branch=self.branch)
        self.atc = User.objects.create_user(username="eq-atc", role=User.Role.ATC, branch=self.branch)
        self.denied = User.objects.create_user(username="eq-denied", role=User.Role.ACCOUNTING, branch=self.branch)
        self.service_type = ServiceType.objects.create(code="EQ-INTERNET", name="Internet prueba")
        self.plan = Plan.objects.create(code="EQ-PLAN", name="Plan prueba", service_type=self.service_type, monthly_price=50)
        self.subscription = self.make_subscription(1)
        self.customer = self.subscription.customer
        self.second = self.make_subscription(2)
        self.foreign = self.make_subscription(3, branch=self.other_branch)
        self.equipment = self.register("QA-001")
        kind, _ = OrderType.objects.get_or_create(code="INSTALLATION", defaults={"name": "Instalación"})
        self.order = WorkOrder.objects.create(order_number="EQ-OT-001", subscription=self.subscription, order_type=kind, created_by=self.atc, branch=self.branch)

    def make_subscription(self, number, branch=None):
        customer = Customer.objects.create(code=f"EQ-C-{number}", branch=branch or self.branch, document_type="DNI", document_number=f"{number:08d}", first_name="Abonado", paternal_surname=f"Prueba {number}")
        address = CustomerAddress.objects.create(customer=customer, address="Dirección de prueba 100", district="Distrito de prueba")
        return Subscription.objects.create(customer=customer, address=address, service_type=self.service_type, plan=self.plan, status=Subscription.Status.ACTIVE)

    def register(self, serial, **kwargs):
        fields = dict(branch=self.branch, user=self.admin, kind="ONT", brand="Marca prueba", model="Modelo QA", serial_number=serial)
        fields.update(kwargs)
        return register_equipment(**fields)

    def assign(self, **kwargs):
        fields = dict(equipment=self.equipment, subscription=self.subscription, branch=self.branch, user=self.atc, operation_id=uuid.uuid4())
        fields.update(kwargs)
        return assign_equipment(**fields)

    def remove(self, assignment, **kwargs):
        fields = dict(assignment=assignment, branch=self.branch, user=self.atc, reason="Retiro de prueba", return_status=Equipment.Status.REVIEW)
        fields.update(kwargs)
        return remove_equipment(**fields)

    def review(self, **kwargs):
        fields = dict(equipment=self.equipment, branch=self.branch, user=self.admin, reason="Equipo revisado y operativo", return_status=Equipment.Status.AVAILABLE, operation_id=uuid.uuid4())
        fields.update(kwargs)
        return review_equipment(**fields)


class EquipmentDomainTests(EquipmentFixtures, TestCase):
    def test_registration_normalizes_identifiers_and_rejects_duplicates(self):
        equipment = self.register(" qa-002 ", mac_address="aabb.ccdd.ee01")
        self.assertEqual(equipment.serial_number, "QA-002")
        self.assertEqual(equipment.mac_address, "AA:BB:CC:DD:EE:01")
        for fields in ({"serial_number": "qa-002"}, {"serial_number": "QA-003", "mac_address": "aa-bb-cc-dd-ee-01"}, {"serial_number": "QA-002", "branch": self.other_branch}):
            serial = fields.pop("serial_number")
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.register(serial, **fields)

    def test_identifiers_and_required_metadata_are_validated(self):
        for fields in ({"serial_number": "", "mac_address": ""}, {"serial_number": "", "mac_address": "not-a-mac"}, {"serial_number": "QA-X", "brand": "  "}, {"serial_number": "QA-Y", "kind": "BAD"}):
            serial = fields.pop("serial_number")
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.register(serial, **fields)
        equipment = self.register("", mac_address="aabbccddee05")
        self.assertEqual(equipment.mac_address, "AA:BB:CC:DD:EE:05")

    def test_assignment_removal_review_and_reassignment_preserve_history(self):
        first = self.assign(work_order=self.order, notes="Instalación de prueba")
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, "ASSIGNED")
        self.assertEqual(first.service_code_snapshot, self.subscription.service_code)
        self.remove(first)
        with self.assertRaises(ValidationError):
            self.assign(subscription=self.second)
        self.review()
        second = self.assign(subscription=self.second)
        first.refresh_from_db()
        self.assertEqual(first.removed_by, self.atc)
        self.assertEqual(first.return_status, "REVIEW")
        self.assertIsNotNone(first.removed_at)
        self.assertIsNone(second.removed_at)
        self.assertEqual(self.equipment.assignments.count(), 2)
        review = EquipmentReview.objects.get()
        self.assertEqual((review.previous_status, review.status), ("REVIEW", "AVAILABLE"))

    def test_assignment_replay_is_idempotent_even_after_retirement(self):
        token = uuid.uuid4()
        first = self.assign(operation_id=token)
        self.assertEqual(self.assign(operation_id=token).pk, first.pk)
        self.remove(first, return_status="AVAILABLE")
        self.assertEqual(self.assign(operation_id=token).pk, first.pk)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, "AVAILABLE")
        self.assertEqual(EquipmentAssignment.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.assign(operation_id=token, subscription=self.second)

    def test_stale_remove_does_not_remove_a_later_assignment(self):
        first = self.assign()
        self.remove(first, return_status="AVAILABLE")
        second = self.assign(subscription=self.second)
        self.remove(first)
        second.refresh_from_db()
        self.equipment.refresh_from_db()
        self.assertIsNone(second.removed_at)
        self.assertEqual(self.equipment.status, "ASSIGNED")

    def test_review_replay_does_not_change_a_later_state(self):
        token = uuid.uuid4()
        self.review(return_status="DAMAGED", operation_id=token)
        self.review()
        self.assign()
        self.review(return_status="DAMAGED", operation_id=token)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, "ASSIGNED")
        self.assertEqual(EquipmentReview.objects.count(), 2)

    def test_device_cannot_be_assigned_twice(self):
        self.assign()
        with self.assertRaises(ValidationError):
            self.assign(subscription=self.second)

    def test_cross_branch_equipment_and_services_are_rejected(self):
        for fields in ({"subscription": self.foreign}, {"branch": self.other_branch}, {"branch": None}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.assign(**fields)
        assignment = self.assign()
        with self.assertRaises(ValidationError):
            self.remove(assignment, branch=self.other_branch)
        self.assertIsNone(EquipmentAssignment.objects.get(pk=assignment.pk).removed_at)

    def test_inactive_customer_subscription_and_cancelled_service_are_rejected(self):
        for model, field, value in ((self.customer, "is_active", False), (self.subscription, "is_active", False), (self.subscription, "status", "CANCELLED")):
            original = getattr(model, field)
            setattr(model, field, value)
            model.save(update_fields=[field])
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                self.assign()
            setattr(model, field, original)
            model.save(update_fields=[field])

    def test_work_order_must_belong_to_exact_subscription(self):
        with self.assertRaises(ValidationError):
            self.assign(subscription=self.second, work_order=self.order)
        self.assertEqual(self.assign(work_order=self.order).work_order_id, self.order.pk)

    def test_removal_requires_reason_and_safe_status(self):
        assignment = self.assign()
        for fields in ({"reason": " "}, {"return_status": "ASSIGNED"}, {"return_status": "BAD"}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.remove(assignment, **fields)
        assignment.refresh_from_db()
        self.assertIsNone(assignment.removed_at)

    def test_review_cannot_change_an_assigned_device(self):
        self.assign()
        with self.assertRaises(ValidationError):
            self.review(return_status="DAMAGED")
        self.assertFalse(EquipmentReview.objects.exists())

    def test_permissions_are_enforced_in_domain(self):
        with self.assertRaises(PermissionDenied):
            self.register("QA-003", user=self.atc)
        with self.assertRaises(PermissionDenied):
            self.assign(user=self.denied)
        assignment = self.assign()
        with self.assertRaises(PermissionDenied):
            self.remove(assignment, user=self.denied)
        self.remove(assignment)
        with self.assertRaises(PermissionDenied):
            self.review(user=self.atc)
        self.atc.is_active = False
        with self.assertRaises(PermissionDenied):
            self.assign(user=self.atc)

    def test_database_prevents_two_open_assignments_and_history_deletion(self):
        self.assign()
        with self.assertRaises(IntegrityError), transaction.atomic():
            EquipmentAssignment.objects.create(equipment=self.equipment, subscription=self.second, service_code_snapshot=self.second.service_code, assigned_by=self.atc)
        with self.assertRaises(ProtectedError):
            self.equipment.delete()
        with self.assertRaises(ProtectedError):
            self.subscription.delete()

    def test_incomplete_registration_and_withdrawal_preserve_equipment_history(self):
        self.subscription.status = "PRESALE"
        self.subscription.save(update_fields=["status"])
        assignment = self.assign()
        self.remove(assignment)
        self.assertTrue(any("equipos" in text for text in incomplete_registration_issues(self.customer)))
        self.assertTrue(any("equipos" in text for text in installation_withdrawal_issues(self.order)))

    def test_transaction_rolls_back_assignment_if_equipment_update_fails(self):
        with patch.object(Equipment, "save", side_effect=RuntimeError("fallo de prueba")):
            with self.assertRaises(RuntimeError):
                self.assign()
        self.assertFalse(EquipmentAssignment.objects.exists())
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, "AVAILABLE")


class EquipmentWebTests(EquipmentFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.atc)
        self.assign_url = reverse("equipment:assign", args=[self.customer.pk])

    def payload(self, **kwargs):
        values = {"equipment": self.equipment.pk, "subscription": self.subscription.pk, "work_order": self.order.pk, "notes": "Prueba", "operation_id": str(uuid.uuid4())}
        values.update(kwargs)
        return values

    def test_login_permission_and_role_boundaries(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("equipment:list")).status_code, 302)
        self.client.force_login(self.denied)
        self.assertEqual(self.client.get(reverse("equipment:list")).status_code, 403)
        self.assertEqual(self.client.post(self.assign_url, self.payload()).status_code, 403)
        self.client.force_login(self.atc)
        self.assertEqual(self.client.get(reverse("equipment:create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("equipment:review", args=[self.equipment.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("equipment:list")).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("equipment:create")).status_code, 200)

    def test_assign_post_replay_and_stale_post_are_safe(self):
        data = self.payload()
        for _ in range(2):
            self.assertEqual(self.client.post(self.assign_url, data).status_code, 302)
        assignment = EquipmentAssignment.objects.get()
        self.remove(assignment, return_status="AVAILABLE")
        self.assertEqual(self.client.post(self.assign_url, data).status_code, 302)
        self.assertEqual(EquipmentAssignment.objects.count(), 1)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, "AVAILABLE")

    def test_invalid_token_and_tampered_subscription_are_rejected(self):
        for data in (self.payload(operation_id="invalid"), self.payload(subscription=self.second.pk), self.payload(subscription=self.foreign.pk)):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(self.assign_url, data).status_code, 400)
        self.assertFalse(EquipmentAssignment.objects.exists())

    def test_branch_is_scoped_for_get_and_post(self):
        assignment = self.assign()
        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = self.other_branch.pk
        session.save()
        paths = [reverse("equipment:detail", args=[self.equipment.pk]), self.assign_url, reverse("equipment:customer", args=[self.customer.pk]), reverse("equipment:remove", args=[assignment.pk])]
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.post(reverse("equipment:remove", args=[assignment.pk]), {"reason": "Intento de prueba", "return_status": "AVAILABLE"}).status_code, 404)
        self.assertNotContains(self.client.get(reverse("equipment:list")), self.equipment.serial_number)

    def test_registration_duplicate_mac_and_success(self):
        self.client.force_login(self.admin)
        data = {"kind": "ROUTER", "brand": "QA", "model": "QA", "serial_number": " qa-new ", "mac_address": "aa-bb-cc-dd-ee-ff"}
        self.assertEqual(self.client.post(reverse("equipment:create"), data).status_code, 302)
        self.assertEqual(self.client.post(reverse("equipment:create"), data).status_code, 400)
        self.assertEqual(Equipment.objects.filter(serial_number="QA-NEW").count(), 1)

    def test_removal_get_is_read_only_and_post_records_audit(self):
        assignment = self.assign()
        url = reverse("equipment:remove", args=[assignment.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        assignment.refresh_from_db()
        self.assertIsNone(assignment.removed_at)
        self.assertEqual(self.client.post(url, {"reason": "Cambio por equipo nuevo", "return_status": "DAMAGED"}).status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.removal_reason, "Cambio por equipo nuevo")
        self.assertTrue(self.atc.audit_events.filter(route_name="equipment:remove", status_code=302).exists())

    def test_review_form_replay_and_history(self):
        self.client.force_login(self.admin)
        url = reverse("equipment:review", args=[self.equipment.pk])
        data = {"reason": "Prueba de revisión", "return_status": "DAMAGED", "operation_id": str(uuid.uuid4())}
        for _ in range(2):
            self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(EquipmentReview.objects.count(), 1)
        self.assertContains(self.client.get(reverse("equipment:detail", args=[self.equipment.pk])), "Prueba de revisión")

    def test_filters_pagination_and_no_branch(self):
        self.register("", mac_address="aabbccddee01")
        response = self.client.get(reverse("equipment:list"), {"q": "aa-bb-cc-dd-ee-01"})
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.get(reverse("equipment:list"), {"status": "BAD"}).status_code, 400)
        with patch("apps.equipment.views.get_active_branch", return_value=None):
            self.assertEqual(self.client.get(reverse("equipment:list")).status_code, 400)
        for number in range(3, 28):
            self.register(f"QA-{number:04d}")
        response = self.client.get(reverse("equipment:list"), {"status": "AVAILABLE", "page": 2})
        self.assertEqual(len(response.context["page_obj"]), 2)
        self.assertContains(response, "status=AVAILABLE")

    def test_customer_tab_links_and_safe_text(self):
        self.assign(notes="<script>bad()</script>")
        response = self.client.get(reverse("equipment:customer", args=[self.customer.pk]))
        self.assertContains(response, "&lt;script&gt;bad()&lt;/script&gt;")
        self.assertContains(response, self.subscription.service_code)
        self.assertContains(response, reverse("equipment:detail", args=[self.equipment.pk]))
        self.assertContains(self.client.get(reverse("customers:detail", args=[self.customer.pk])), reverse("equipment:customer", args=[self.customer.pk]))

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.atc)
        self.assertEqual(client.post(self.assign_url, self.payload()).status_code, 403)
        self.assertFalse(EquipmentAssignment.objects.exists())


@skipUnless(connection.vendor == "postgresql", "Requiere bloqueos reales de PostgreSQL")
class EquipmentConcurrencyTests(EquipmentFixtures, TransactionTestCase):
    def test_only_one_simultaneous_assignment_wins(self):
        barrier = Barrier(2)

        def worker(subscription_id):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.atc.pk)
                equipment = Equipment.objects.get(pk=self.equipment.pk)
                subscription = Subscription.objects.get(pk=subscription_id)
                branch = Branch.objects.get(pk=self.branch.pk)
                barrier.wait(timeout=10)
                try:
                    assign_equipment(equipment=equipment, subscription=subscription, branch=branch, user=user, operation_id=uuid.uuid4())
                    return "assigned"
                except ValidationError:
                    return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(worker, [self.subscription.pk, self.second.pk]))
        self.assertCountEqual(outcomes, ["assigned", "rejected"])
        self.assertEqual(EquipmentAssignment.objects.filter(removed_at__isnull=True).count(), 1)
