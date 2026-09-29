from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import LegacyRecord, LegacyRecordCorrection


class LegacyRecordTests(TestCase):
    def test_payload_original_no_se_puede_reescribir(self):
        record = LegacyRecord.objects.create(
            entity_type=LegacyRecord.EntityType.WORK_ORDER,
            legacy_id="102353",
            raw_payload={"codigo": 102353, "estado": "A"},
            normalized_payload={"status": "ATTENDED"},
        )

        record.raw_payload = {"codigo": 102353, "estado": "U"}

        with self.assertRaises(ValidationError):
            record.save()

    def test_correccion_normalizada_conserva_antes_despues_y_motivo(self):
        record = LegacyRecord.objects.create(
            entity_type=LegacyRecord.EntityType.PAYMENT,
            legacy_id="0524102",
            raw_payload={"total": "52.40"},
            normalized_payload={"amount": "52.40"},
        )

        correction = record.apply_normalized_correction(
            {"amount": "52.50"},
            reason="Monto validado contra el comprobante físico.",
        )

        record.refresh_from_db()
        self.assertEqual(record.normalized_payload, {"amount": "52.50"})
        self.assertEqual(
            record.review_status,
            LegacyRecord.ReviewStatus.CORRECTED,
        )
        self.assertEqual(LegacyRecordCorrection.objects.count(), 1)
        self.assertEqual(correction.previous_payload, {"amount": "52.40"})
        self.assertEqual(correction.new_payload, {"amount": "52.50"})

    def test_correccion_exige_motivo(self):
        record = LegacyRecord.objects.create(
            entity_type=LegacyRecord.EntityType.CONTRACT,
            legacy_id="8610",
            raw_payload={"estado": "A"},
            normalized_payload={"status": "ACTIVE"},
        )

        with self.assertRaises(ValidationError):
            record.apply_normalized_correction(
                {"status": "CANCELLED"},
                reason="",
            )
