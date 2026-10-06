"""El registro manual retirado no vuelve a abrir operaciones por URLs antiguas."""

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.organization.models import Branch

from .models import Equipment, EquipmentAssignment, EquipmentReview


class RetiredEquipmentRegistryTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="EQ-ARCHIVE", name="Sede de prueba")
        self.user = User.objects.create_user(username="archive-admin", role=User.Role.ADMIN, branch=self.branch, is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.record = Equipment.objects.create(branch=self.branch, kind="ONT", brand="Muestra", model="Archivo QA", serial_number="QA-ARCHIVE-001", created_by=self.user)

    def test_old_get_and_post_routes_are_retired_even_for_superuser(self):
        paths = ["/equipos/", "/equipos/registrar/", f"/equipos/{self.record.pk}/", f"/equipos/{self.record.pk}/revisar/", "/equipos/abonado/1/", "/equipos/abonado/1/asignar/", "/equipos/asignacion/1/retirar/"]
        for path in paths:
            for method in (self.client.get, self.client.post):
                with self.subTest(path=path, method=method.__name__):
                    self.assertEqual(method(path).status_code, 404)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, Equipment.Status.AVAILABLE)
        self.assertEqual(Equipment.objects.count(), 1)
        self.assertEqual(EquipmentAssignment.objects.count(), 0)
        self.assertEqual(EquipmentReview.objects.count(), 0)

    def test_sidebar_and_customer_tabs_no_longer_offer_registry(self):
        customer = Customer.objects.create(code="EQ-ARCHIVE-C", branch=self.branch, document_type="DNI", document_number="00000001", first_name="Abonado", paternal_surname="Prueba")
        for url in (reverse("customers:search"), reverse("customers:detail", args=[customer.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'href="/equipos/')
                self.assertNotContains(response, "Equipos de abonados")

    def test_preserved_archive_has_no_admin_write_actions(self):
        request = RequestFactory().get("/admin/")
        request.user = self.user
        for model in (Equipment, EquipmentAssignment, EquipmentReview):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
