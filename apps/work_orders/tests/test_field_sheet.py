"""
Pruebas de la ficha técnica de campo (WorkOrderFieldSheet).

Cubren tres capas:

- services.update_field_sheet() / services.add_work_order_evidence(): quién
  puede escribir, cuándo, y qué rechazan.
- apps.work_orders.location.resolve_location_display(): la regla de GPS
  válido / inválido de la ficha OT.
- WorkOrderDetailView: la ficha web -acceso de ATC vs. técnico, solo lectura
  para uno y edición para el otro, y que un POST manipulado no se salte las
  reglas del servicio.
"""

from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.work_orders.location import resolve_location_display
from apps.work_orders.models import WorkOrder, WorkOrderEvidence, WorkOrderFieldSheet
from apps.work_orders.services import add_work_order_evidence, update_field_sheet
from apps.work_orders.tests.base import WorkOrderTestCase


class UpdateFieldSheetServiceTests(WorkOrderTestCase):
    """services.update_field_sheet(): único camino legítimo de escritura."""

    def setUp(self):
        super().setUp()

        self.order = self.create_assigned_order()

    def test_assigned_technician_can_create_the_sheet(self):
        sheet = update_field_sheet(
            self.order,
            user=self.technician,
            nap="NAP-014",
            terminal="5",
            equipment_code="AA:BB:CC:DD:EE:FF",
            seal_number="PRC-000123",
            notes="Se dejó el equipo operativo.",
        )

        sheet.refresh_from_db()

        self.assertEqual(sheet.work_order, self.order)
        self.assertEqual(sheet.nap, "NAP-014")
        self.assertEqual(sheet.terminal, "5")
        self.assertEqual(sheet.equipment_code, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(sheet.seal_number, "PRC-000123")
        self.assertEqual(sheet.notes, "Se dejó el equipo operativo.")
        self.assertEqual(sheet.updated_by, self.technician)

    def test_second_call_updates_the_same_sheet(self):
        """Un OneToOneField: nunca hay dos fichas para la misma orden."""
        update_field_sheet(self.order, user=self.technician, nap="NAP-014")
        update_field_sheet(self.order, user=self.technician, nap="NAP-020")

        self.assertEqual(
            WorkOrderFieldSheet.objects.filter(work_order=self.order).count(),
            1,
        )

        sheet = WorkOrderFieldSheet.objects.get(work_order=self.order)
        self.assertEqual(sheet.nap, "NAP-020")

    def test_partial_update_keeps_other_fields(self):
        update_field_sheet(self.order, user=self.technician, nap="NAP-014")
        update_field_sheet(self.order, user=self.technician, terminal="8")

        sheet = WorkOrderFieldSheet.objects.get(work_order=self.order)

        self.assertEqual(sheet.nap, "NAP-014")
        self.assertEqual(sheet.terminal, "8")

    def test_unassigned_technician_is_rejected(self):
        with self.assertRaises(ValidationError):
            update_field_sheet(self.order, user=self.other_technician, nap="X")

        self.assertFalse(
            WorkOrderFieldSheet.objects.filter(work_order=self.order).exists()
        )

    def test_atc_user_is_rejected(self):
        """ATC no edita campos técnicos ni siquiera intentándolo por fuera de la UI."""
        with self.assertRaises(ValidationError):
            update_field_sheet(self.order, user=self.atc_user, nap="X")

    def test_inactive_technician_is_rejected(self):
        self.order.assigned_technician = self.inactive_technician
        self.order.save(update_fields=["assigned_technician"])

        with self.assertRaises(ValidationError):
            update_field_sheet(self.order, user=self.inactive_technician, nap="X")

    def test_closed_order_is_rejected(self):
        order = self.create_attended_order()

        with self.assertRaises(ValidationError):
            update_field_sheet(order, user=self.technician, nap="X")

    def test_in_progress_order_can_still_be_edited(self):
        """La ficha se completa DURANTE la atención, antes de liquidar."""
        order = self.create_order_in_progress()

        sheet = update_field_sheet(order, user=self.technician, nap="NAP-030")

        self.assertEqual(sheet.nap, "NAP-030")

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(ValidationError):
            update_field_sheet(self.order, user=self.technician, status="LIQUIDATED")

        self.assertFalse(
            WorkOrderFieldSheet.objects.filter(work_order=self.order).exists()
        )


class AddWorkOrderEvidenceServiceTests(WorkOrderTestCase):
    """services.add_work_order_evidence(): mismo criterio de autorización."""

    def setUp(self):
        super().setUp()

        self.order = self.create_assigned_order()

    def _file(self, name="evidencia.jpg"):
        return SimpleUploadedFile(name, b"contenido-de-prueba", content_type="image/jpeg")

    def test_assigned_technician_can_attach_evidence(self):
        evidence = add_work_order_evidence(
            self.order,
            user=self.technician,
            file=self._file(),
            description="Foto del NAP",
        )

        self.assertEqual(evidence.work_order, self.order)
        self.assertEqual(evidence.uploaded_by, self.technician)
        self.assertIsNone(evidence.liquidation)
        self.assertEqual(evidence.description, "Foto del NAP")

    def test_unassigned_technician_is_rejected(self):
        with self.assertRaises(ValidationError):
            add_work_order_evidence(
                self.order,
                user=self.other_technician,
                file=self._file(),
            )

        self.assertFalse(WorkOrderEvidence.objects.exists())

    def test_closed_order_is_rejected(self):
        order = self.create_attended_order()

        with self.assertRaises(ValidationError):
            add_work_order_evidence(order, user=self.technician, file=self._file())

    def test_missing_file_is_rejected(self):
        with self.assertRaises(ValidationError):
            add_work_order_evidence(self.order, user=self.technician, file=None)


class LocationDisplayTests(WorkOrderTestCase):
    """
    resolve_location_display(): dirección textual siempre, y GPS válido
    solo con coordenadas reales -nunca inventadas ni sobrescritas.
    """

    def test_valid_coordinates_produce_a_maps_link_by_coordinates(self):
        self.address.latitude = Decimal("-11.7669000")
        self.address.longitude = Decimal("-77.2069000")
        self.address.save()

        result = resolve_location_display(self.address)

        self.assertTrue(result["has_valid_gps"])
        self.assertIn("-11.7669000", result["maps_url"])
        self.assertIn("-77.2069000", result["maps_url"])
        self.assertEqual(result["gps_label"], "Abrir en Google Maps")

    def test_missing_coordinates_are_invalid(self):
        self.address.latitude = None
        self.address.longitude = None
        self.address.save()

        result = resolve_location_display(self.address)

        self.assertFalse(result["has_valid_gps"])
        self.assertEqual(result["gps_label"], "GPS no disponible")
        # Sin coordenadas, el enlace de Maps busca por la dirección textual.
        self.assertIn("Av.", result["maps_url"])

    def test_zero_zero_coordinates_are_treated_as_invalid(self):
        self.address.latitude = Decimal("0")
        self.address.longitude = Decimal("0")
        self.address.save()

        result = resolve_location_display(self.address)

        self.assertFalse(result["has_valid_gps"])

    def test_zero_with_many_decimals_is_still_invalid(self):
        """0.0000000 sigue siendo cero, no una coordenada real."""
        self.address.latitude = Decimal("0.0000000")
        self.address.longitude = Decimal("0.0000000")
        self.address.save()

        result = resolve_location_display(self.address)

        self.assertFalse(result["has_valid_gps"])

    def test_only_one_axis_zero_is_invalid_for_this_provider(self):
        """Distriluz usa cero como centinela de ausencia de georreferencia.

        En el SICV operativo no se publica un par parcial/centinela aunque el
        otro eje tenga valor: una ubicación dudosa no debe parecer exacta.
        """
        self.address.latitude = Decimal("0")
        self.address.longitude = Decimal("-77.2069000")
        self.address.save()

        result = resolve_location_display(self.address)

        self.assertFalse(result["has_valid_gps"])

    def test_address_text_is_always_present_regardless_of_gps(self):
        self.address.latitude = None
        self.address.longitude = None
        self.address.save()

        result = resolve_location_display(self.address)

        self.assertIn(self.address.address, result["text"])
        self.assertIn(self.address.district, result["text"])

    def test_never_writes_back_to_the_address(self):
        """La función solo decide cómo mostrar; nunca corrige ni inventa."""
        self.address.latitude = None
        self.address.longitude = None
        self.address.save()

        resolve_location_display(self.address)

        self.address.refresh_from_db()

        self.assertIsNone(self.address.latitude)
        self.assertIsNone(self.address.longitude)

    def test_none_address_does_not_crash(self):
        result = resolve_location_display(None)

        self.assertEqual(result["text"], "")
        self.assertFalse(result["has_valid_gps"])
        self.assertEqual(result["maps_url"], "")


class WorkOrderDetailViewAccessTests(WorkOrderTestCase):
    """Quién puede abrir la ficha, y en qué modo."""

    def setUp(self):
        super().setUp()

        self.order = self.create_assigned_order()
        self.url = reverse("work_orders:detail", kwargs={"pk": self.order.pk})

        self.view_permission = Permission.objects.get(
            codename="view_workorder",
            content_type__app_label="work_orders",
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_staff_with_view_permission_sees_the_order_read_only(self):
        self.atc_user.user_permissions.add(self.view_permission)
        self.client.login(username="atc1", password="test1234")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_edit"])
        self.assertFalse(response.context["is_owner_technician"])

    def test_assigned_technician_can_edit(self):
        self.client.login(username="tecnico1", password="test1234")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_edit"])
        self.assertTrue(response.context["is_owner_technician"])

    def test_other_technician_is_forbidden(self):
        self.client.login(username="tecnico2", password="test1234")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_atc_without_permission_is_forbidden(self):
        self.client.login(username="atc1", password="test1234")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_unknown_order_returns_not_found_for_staff(self):
        self.atc_user.user_permissions.add(self.view_permission)
        self.client.login(username="atc1", password="test1234")

        url = reverse("work_orders:detail", kwargs={"pk": self.order.pk + 999})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_closed_order_is_read_only_even_for_the_assigned_technician(self):
        order = self.create_attended_order()
        url = reverse("work_orders:detail", kwargs={"pk": order.pk})

        self.client.login(username="tecnico1", password="test1234")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_owner_technician"])
        self.assertFalse(response.context["can_edit"])


class WorkOrderDetailViewContentTests(WorkOrderTestCase):
    """Lo que la ficha muestra: cliente, plan, dirección, GPS, suministro."""

    def setUp(self):
        super().setUp()

        self.address.electrical_supply_code = "SUM-000123"
        self.address.latitude = None
        self.address.longitude = None
        self.address.save()

        self.order = self.create_assigned_order()
        self.url = reverse("work_orders:detail", kwargs={"pk": self.order.pk})

        self.client.login(username="tecnico1", password="test1234")

    def test_shows_customer_plan_and_address(self):
        response = self.client.get(self.url)

        self.assertContains(response, self.customer.code)
        self.assertContains(response, self.plan.name)
        self.assertContains(response, self.address.address)

    def test_shows_supply_code(self):
        response = self.client.get(self.url)

        self.assertContains(response, "SUM-000123")

    def test_shows_gps_not_available_when_coordinates_are_missing(self):
        response = self.client.get(self.url)

        self.assertContains(response, "GPS no disponible")

    def test_shows_maps_link_with_valid_coordinates(self):
        self.address.latitude = Decimal("-11.7669000")
        self.address.longitude = Decimal("-77.2069000")
        self.address.save()

        response = self.client.get(self.url)

        self.assertContains(response, "Abrir en Google Maps")
        self.assertContains(response, "-11.7669000")


class WorkOrderDetailViewReadOnlyForAtcTests(WorkOrderTestCase):
    """ATC consulta, nunca edita campos técnicos."""

    def setUp(self):
        super().setUp()

        self.order = self.create_assigned_order()
        self.url = reverse("work_orders:detail", kwargs={"pk": self.order.pk})

        self.atc_user.user_permissions.add(
            Permission.objects.get(
                codename="view_workorder",
                content_type__app_label="work_orders",
            )
        )
        self.client.login(username="atc1", password="test1234")

    def test_no_edit_form_is_offered(self):
        response = self.client.get(self.url)

        self.assertNotContains(response, "Guardar ficha técnica")
        self.assertNotContains(response, "Adjuntar evidencia")

    def test_post_is_forbidden_even_with_a_crafted_action(self):
        response = self.client.post(
            self.url,
            {"action": "save_field_sheet", "nap": "NAP-999"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            WorkOrderFieldSheet.objects.filter(work_order=self.order).exists()
        )


class WorkOrderDetailViewTechnicianEditTests(WorkOrderTestCase):
    """El técnico asignado completa NAP, borne, MAC/equipo, precinto y notas."""

    def setUp(self):
        super().setUp()

        self.order = self.create_assigned_order()
        self.url = reverse("work_orders:detail", kwargs={"pk": self.order.pk})

        self.client.login(username="tecnico1", password="test1234")

    def test_saving_the_field_sheet_persists_the_values(self):
        response = self.client.post(
            self.url,
            {
                "action": "save_field_sheet",
                "nap": "NAP-014",
                "terminal": "5",
                "equipment_code": "AA:BB:CC:DD:EE:FF",
                "seal_number": "PRC-000123",
                "notes": "Instalación completada sin observaciones.",
            },
        )

        self.assertRedirects(response, self.url)

        sheet = WorkOrderFieldSheet.objects.get(work_order=self.order)

        self.assertEqual(sheet.nap, "NAP-014")
        self.assertEqual(sheet.seal_number, "PRC-000123")
        self.assertEqual(sheet.updated_by, self.technician)

    def test_uploading_evidence_persists_the_file(self):
        upload = SimpleUploadedFile(
            "foto.jpg", b"contenido", content_type="image/jpeg"
        )

        response = self.client.post(
            self.url,
            {
                "action": "upload_evidence",
                "file": upload,
                "description": "NAP instalado",
            },
        )

        self.assertRedirects(response, self.url)

        evidence = WorkOrderEvidence.objects.get(work_order=self.order)
        self.assertEqual(evidence.uploaded_by, self.technician)
        self.assertEqual(evidence.description, "NAP instalado")

    def test_other_technicians_order_cannot_be_edited(self):
        foreign_order = self.create_order()
        foreign_order.assign_technician(
            technician=self.other_technician,
            assigned_by=self.supervisor,
        )

        url = reverse("work_orders:detail", kwargs={"pk": foreign_order.pk})

        response = self.client.post(
            url,
            {"action": "save_field_sheet", "nap": "NAP-999"},
        )

        self.assertEqual(response.status_code, 403)

    def test_closed_order_rejects_the_post(self):
        order = self.create_attended_order()
        url = reverse("work_orders:detail", kwargs={"pk": order.pk})

        response = self.client.post(
            url,
            {"action": "save_field_sheet", "nap": "NAP-999"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            WorkOrderFieldSheet.objects.filter(work_order=order).exists()
        )

    def test_gps_coordinates_are_never_written_by_this_view(self):
        """
        La ficha nunca escribe CustomerAddress: guardar la ficha técnica
        no toca latitude/longitude de ninguna manera.
        """
        self.client.post(
            self.url,
            {"action": "save_field_sheet", "nap": "NAP-014"},
        )

        self.address.refresh_from_db()

        self.assertIsNone(self.address.latitude)
        self.assertIsNone(self.address.longitude)
