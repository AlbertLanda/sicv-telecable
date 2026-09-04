"""Pruebas de integración API: claim -> start -> ficha -> materiales -> evidencias."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.inventory.models import Material, WorkOrderMaterialMovement
from apps.work_orders.models import WorkOrder, WorkOrderFieldSheet
from apps.work_orders.tests.base import WorkOrderTestCase


class TechnicianFieldWorkflowAPITests(WorkOrderTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        token, _ = Token.objects.get_or_create(user=self.technician)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def url(self, name, order):
        return reverse(f"work_orders_api:{name}", args=[order.pk])

    def test_assigned_technician_can_start_own_order(self):
        order = self.create_assigned_order()

        response = self.api.post(
            self.url("start", order),
            {"remarks": "Inicio atención en domicilio."},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)
        self.assertIsNotNone(order.started_at)

    def test_field_sheet_is_blocked_before_start(self):
        order = self.create_assigned_order()

        response = self.api.patch(
            self.url("field_sheet", order),
            {"nap": "NAP-014", "terminal": "5"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(
            WorkOrderFieldSheet.objects.filter(work_order=order).exists()
        )

    def test_technician_updates_same_field_sheet_after_start(self):
        order = self.create_assigned_order()
        self.api.post(self.url("start", order), {}, format="json")

        first = self.api.patch(
            self.url("field_sheet", order),
            {"nap": "NAP-014", "terminal": "5"},
            format="json",
        )
        second = self.api.patch(
            self.url("field_sheet", order),
            {"equipment_code": "AA:BB:CC:DD:EE:FF"},
            format="json",
        )

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(
            WorkOrderFieldSheet.objects.filter(work_order=order).count(),
            1,
        )
        sheet = WorkOrderFieldSheet.objects.get(work_order=order)
        self.assertEqual(sheet.nap, "NAP-014")
        self.assertEqual(sheet.terminal, "5")
        self.assertEqual(sheet.equipment_code, "AA:BB:CC:DD:EE:FF")

    def test_other_technician_cannot_access_field_sheet(self):
        order = self.create_assigned_order()
        token, _ = Token.objects.get_or_create(user=self.other_technician)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.api.get(self.url("field_sheet", order))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_field_materials_are_blocked_before_start(self):
        order = self.create_assigned_order()
        material = Material.objects.get(code="CABLE_RG6")

        response = self.api.post(
            self.url("field_materials", order),
            {
                "material_id": material.pk,
                "movement_type": "INSTALLED",
                "quantity": "12.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(
            WorkOrderMaterialMovement.objects.filter(work_order=order).exists()
        )

    def test_field_materials_keep_installed_and_removed_separate(self):
        order = self.create_assigned_order()
        self.api.post(self.url("start", order), {}, format="json")
        material = Material.objects.get(code="CABLE_RG6")

        installed = self.api.post(
            self.url("field_materials", order),
            {
                "material_id": material.pk,
                "movement_type": "INSTALLED",
                "quantity": "20.00",
                "remarks": "Tendido nuevo.",
            },
            format="json",
        )
        removed = self.api.post(
            self.url("field_materials", order),
            {
                "material_id": material.pk,
                "movement_type": "REMOVED",
                "quantity": "4.00",
                "remarks": "Cable deteriorado.",
            },
            format="json",
        )
        listing = self.api.get(self.url("field_materials", order))

        self.assertEqual(installed.status_code, status.HTTP_200_OK)
        self.assertEqual(removed.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(len(listing.data["installed"]), 1)
        self.assertEqual(len(listing.data["removed"]), 1)
        self.assertEqual(listing.data["installed"][0]["material"]["code"], "CABLE_RG6")
        self.assertEqual(listing.data["removed"][0]["material"]["code"], "CABLE_RG6")
        self.assertEqual(
            WorkOrderMaterialMovement.objects.filter(work_order=order).count(),
            2,
        )

    def test_reposting_same_field_material_updates_quantity_without_duplicate(self):
        order = self.create_assigned_order()
        self.api.post(self.url("start", order), {}, format="json")
        material = Material.objects.get(code="CONECTOR_F56")
        payload = {
            "material_id": material.pk,
            "movement_type": "INSTALLED",
            "quantity": "2.00",
        }

        first = self.api.post(self.url("field_materials", order), payload, format="json")
        payload["quantity"] = "5.00"
        second = self.api.post(self.url("field_materials", order), payload, format="json")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        movements = WorkOrderMaterialMovement.objects.filter(
            work_order=order,
            material=material,
            movement_type=WorkOrderMaterialMovement.MovementType.INSTALLED,
        )
        self.assertEqual(movements.count(), 1)
        self.assertEqual(str(movements.get().quantity), "5.00")

    def test_assigned_technician_can_delete_field_material_during_attention(self):
        order = self.create_assigned_order()
        self.api.post(self.url("start", order), {}, format="json")
        material = Material.objects.get(code="SPLITTER_2")
        created = self.api.post(
            self.url("field_materials", order),
            {
                "material_id": material.pk,
                "movement_type": "REMOVED",
                "quantity": "1.00",
            },
            format="json",
        )
        movement_id = created.data["item"]["id"]

        response = self.api.delete(
            self.url("field_materials", order),
            {"movement_id": movement_id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            WorkOrderMaterialMovement.objects.filter(pk=movement_id).exists()
        )
        self.assertEqual(response.data["removed"], [])

    def test_other_technician_cannot_access_field_materials(self):
        order = self.create_assigned_order()
        token, _ = Token.objects.get_or_create(user=self.other_technician)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.api.get(self.url("field_materials", order))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_evidence_requires_in_progress(self):
        order = self.create_assigned_order()
        image = SimpleUploadedFile(
            "nap.jpg",
            b"imagen-de-prueba",
            content_type="image/jpeg",
        )

        response = self.api.post(
            self.url("evidences", order),
            {"file": image, "description": "NAP"},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_evidence_upload_after_start(self):
        order = self.create_assigned_order()
        self.api.post(self.url("start", order), {}, format="json")
        image = SimpleUploadedFile(
            "nap.jpg",
            b"imagen-de-prueba",
            content_type="image/jpeg",
        )

        response = self.api.post(
            self.url("evidences", order),
            {"file": image, "description": "Foto de la NAP"},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(order.evidences.count(), 1)
        self.assertEqual(order.evidences.first().uploaded_by, self.technician)

    def test_evidence_rejects_unsupported_extension(self):
        order = self.create_assigned_order()
        self.api.post(self.url("start", order), {}, format="json")
        file = SimpleUploadedFile(
            "evidencia.exe",
            b"no-valido",
            content_type="application/octet-stream",
        )

        response = self.api.post(
            self.url("evidences", order),
            {"file": file},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(order.evidences.count(), 0)
