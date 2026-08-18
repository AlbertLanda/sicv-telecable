"""
Pruebas del ciclo de revisión de la liquidación técnica (fase 6).

Cubren la validación única y la única oportunidad de corrección:

    LIQUIDATED -> SUBMITTED -> VALIDATED
                    |
                    +-> CORRECTION_REQUESTED -> RESUBMITTED -> VALIDATED

El orden y la numeración de las pruebas siguen el checklist obligatorio de la
actividad. Validar la liquidación NO cierra la orden: eso es una fase
posterior, y aquí se verifica esa separación.
"""

from django.core.exceptions import ValidationError
from django.db.models.signals import post_save

from apps.work_orders.models import (
    WorkOrder,
    WorkOrderLiquidation,
    WorkOrderLiquidationCorrection,
)
from apps.work_orders.services import (
    request_liquidation_correction,
    resubmit_liquidation,
    submit_liquidation,
    validate_liquidation,
)
from apps.work_orders.tests.base import WorkOrderTestCase

ReviewStatus = WorkOrderLiquidation.ReviewStatus


class LiquidationSubmissionTests(WorkOrderTestCase):
    """Envío formal de la liquidación a revisión."""

    def test_liquidation_can_be_submitted(self):
        """1. La liquidación puede enviarse a SUBMITTED."""
        liquidation = self.create_liquidation()

        self.assertEqual(liquidation.review_status, ReviewStatus.LIQUIDATED)

        submit_liquidation(liquidation, user=self.technician)

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.review_status, ReviewStatus.SUBMITTED)
        self.assertEqual(liquidation.submitted_by, self.technician)
        self.assertIsNotNone(liquidation.submitted_at)

    def test_submitted_liquidation_is_locked_for_free_editing(self):
        """2. Una liquidación SUBMITTED queda bloqueada para edición libre."""
        liquidation = self.create_submitted_liquidation()

        self.assertTrue(liquidation.is_locked)
        self.assertFalse(liquidation.is_editable)

        # Sin una corrección solicitada, el técnico no puede tocarla.
        with self.assertRaises(ValidationError):
            resubmit_liquidation(
                liquidation,
                technician=self.technician,
                changes={"equipment_serial": "XYZ987"},
            )

        # Y tampoco puede reenviarse a revisión una segunda vez.
        with self.assertRaises(ValidationError):
            submit_liquidation(liquidation, user=self.technician)


class LiquidationValidationTests(WorkOrderTestCase):
    """Validación única por permiso funcional."""

    def test_authorized_validator_can_validate_submitted_liquidation(self):
        """3. Un validador autorizado puede validar desde SUBMITTED."""
        liquidation = self.create_submitted_liquidation()

        validate_liquidation(liquidation, validator=self.validator)

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.review_status, ReviewStatus.VALIDATED)
        self.assertTrue(liquidation.is_validated)

    def test_user_without_permission_cannot_validate(self):
        """4. Un usuario sin el permiso funcional no puede validar."""
        liquidation = self.create_submitted_liquidation()

        # Mismo rol que el validador autorizado: lo único que cambia es el
        # permiso, que es exactamente lo que debe decidir.
        self.assertEqual(
            self.unauthorized_validator.role,
            self.validator.role,
        )

        with self.assertRaises(ValidationError):
            validate_liquidation(
                liquidation,
                validator=self.unauthorized_validator,
            )

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.review_status, ReviewStatus.SUBMITTED)
        self.assertIsNone(liquidation.validated_by)

    def test_validation_records_validated_by(self):
        """5. La validación registra validated_by."""
        liquidation = self.create_submitted_liquidation()

        validate_liquidation(liquidation, validator=self.validator)

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.validated_by, self.validator)

    def test_validation_records_validated_at(self):
        """6. La validación registra validated_at."""
        liquidation = self.create_submitted_liquidation()

        validate_liquidation(liquidation, validator=self.validator)

        liquidation.refresh_from_db()

        self.assertIsNotNone(liquidation.validated_at)
        self.assertGreaterEqual(
            liquidation.validated_at,
            liquidation.submitted_at,
        )

    def test_validated_liquidation_cannot_return_to_submitted(self):
        """7. Una liquidación VALIDATED no puede volver a SUBMITTED."""
        liquidation = self.create_validated_liquidation()

        with self.assertRaises(ValidationError):
            submit_liquidation(liquidation, user=self.technician)

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.review_status, ReviewStatus.VALIDATED)

    def test_validation_does_not_close_the_work_order(self):
        """
        La validación NO cierra la orden.

        El cierre definitivo de WorkOrder es una fase posterior todavía sin
        definir: la orden conserva su estado operativo LIQUIDATED.
        """
        liquidation = self.create_validated_liquidation()

        liquidation.work_order.refresh_from_db()

        self.assertEqual(
            liquidation.work_order.status,
            WorkOrder.Status.LIQUIDATED,
        )


class LiquidationCorrectionRequestTests(WorkOrderTestCase):
    """Solicitud de la única corrección."""

    def test_validator_can_request_correction_from_submitted(self):
        """8. El validador puede solicitar corrección desde SUBMITTED."""
        liquidation = self.create_submitted_liquidation()

        request_liquidation_correction(
            liquidation,
            validator=self.validator,
            reason="Serie de ONU incorrecta",
        )

        liquidation.refresh_from_db()

        self.assertEqual(
            liquidation.review_status,
            ReviewStatus.CORRECTION_REQUESTED,
        )
        self.assertTrue(liquidation.has_pending_correction)

    def test_correction_reason_is_mandatory(self):
        """9. El motivo de corrección es obligatorio."""
        liquidation = self.create_submitted_liquidation()

        for empty_reason in ("", "   ", None):
            with self.subTest(reason=repr(empty_reason)):
                with self.assertRaises(ValidationError):
                    request_liquidation_correction(
                        liquidation,
                        validator=self.validator,
                        reason=empty_reason,
                    )

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.review_status, ReviewStatus.SUBMITTED)

    def test_correction_request_records_requested_by(self):
        """10. Se registra correction_requested_by."""
        liquidation = self.create_liquidation_awaiting_correction()

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.correction_requested_by, self.validator)

    def test_correction_request_records_requested_at(self):
        """11. Se registra correction_requested_at."""
        liquidation = self.create_liquidation_awaiting_correction()

        liquidation.refresh_from_db()

        self.assertIsNotNone(liquidation.correction_requested_at)

    def test_correction_request_stores_the_reason(self):
        """12. Se guarda correction_reason."""
        liquidation = self.create_liquidation_awaiting_correction(
            reason="La serie declarada no corresponde a la ONU instalada",
        )

        liquidation.refresh_from_db()

        self.assertEqual(
            liquidation.correction_reason,
            "La serie declarada no corresponde a la ONU instalada",
        )

    def test_correction_cannot_be_requested_when_already_consumed(self):
        """13. No se puede solicitar corrección si correction_count ya es 1."""
        liquidation = self.create_resubmitted_liquidation()

        self.assertEqual(liquidation.correction_count, 1)

        # Se fuerza el estado por fuera de los servicios para aislar la
        # guarda de correction_count: es la única forma de llegar a SUBMITTED
        # con la oportunidad ya consumida.
        WorkOrderLiquidation.objects.filter(pk=liquidation.pk).update(
            review_status=ReviewStatus.SUBMITTED,
        )

        liquidation.refresh_from_db()

        with self.assertRaises(ValidationError):
            request_liquidation_correction(
                liquidation,
                validator=self.validator,
                reason="Segundo intento de corrección",
            )


class LiquidationResubmissionTests(WorkOrderTestCase):
    """Única oportunidad de edición del técnico y reenvío."""

    def test_technician_can_correct_when_correction_requested(self):
        """14. El técnico puede corregir cuando el estado es CORRECTION_REQUESTED."""
        liquidation = self.create_liquidation_awaiting_correction()

        self.assertTrue(liquidation.is_editable)

        resubmit_liquidation(
            liquidation,
            technician=self.technician,
            changes={"equipment_serial": "XYZ987"},
        )

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.equipment_serial, "XYZ987")

    def test_unauthorized_user_cannot_correct(self):
        """15. Otro usuario no autorizado no puede corregir."""
        liquidation = self.create_liquidation_awaiting_correction()

        for intruder in (self.other_technician, self.atc_user, self.validator):
            with self.subTest(user=intruder.username):
                with self.assertRaises(ValidationError):
                    resubmit_liquidation(
                        liquidation,
                        technician=intruder,
                        changes={"equipment_serial": "HACK000"},
                    )

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.equipment_serial, "ABC123")
        self.assertEqual(liquidation.correction_count, 0)

    def test_resubmission_changes_status_to_resubmitted(self):
        """16. El reenvío cambia el estado a RESUBMITTED."""
        liquidation = self.create_resubmitted_liquidation()

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.review_status, ReviewStatus.RESUBMITTED)

    def test_resubmission_increments_correction_count(self):
        """17. El reenvío incrementa correction_count a 1."""
        liquidation = self.create_liquidation_awaiting_correction()

        self.assertEqual(liquidation.correction_count, 0)

        resubmit_liquidation(
            liquidation,
            technician=self.technician,
            changes={"equipment_serial": "XYZ987"},
        )

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.correction_count, 1)
        self.assertFalse(liquidation.correction_available)

    def test_resubmission_records_resubmitted_at(self):
        """18. El reenvío registra resubmitted_at."""
        liquidation = self.create_resubmitted_liquidation()

        liquidation.refresh_from_db()

        self.assertIsNotNone(liquidation.resubmitted_at)
        self.assertGreaterEqual(
            liquidation.resubmitted_at,
            liquidation.correction_requested_at,
        )

    def test_second_correction_is_never_allowed(self):
        """19. No se permite un segundo reenvío ni una segunda corrección."""
        liquidation = self.create_resubmitted_liquidation()

        with self.assertRaises(ValidationError):
            resubmit_liquidation(
                liquidation,
                technician=self.technician,
                changes={"equipment_serial": "SEGUNDO"},
            )

        with self.assertRaises(ValidationError):
            request_liquidation_correction(
                liquidation,
                validator=self.validator,
                reason="Segunda corrección",
            )

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.correction_count, 1)
        self.assertEqual(liquidation.review_status, ReviewStatus.RESUBMITTED)

    def test_resubmitted_liquidation_can_be_validated(self):
        """20. Puede validarse una liquidación RESUBMITTED."""
        liquidation = self.create_resubmitted_liquidation()

        self.assertTrue(liquidation.can_be_validated)

        validate_liquidation(liquidation, validator=self.validator)

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.review_status, ReviewStatus.VALIDATED)
        self.assertEqual(liquidation.correction_count, 1)

    def test_validated_liquidation_rejects_any_edition(self):
        """21. Después de VALIDATED no se permite edición."""
        liquidation = self.create_validated_liquidation()

        self.assertTrue(liquidation.is_locked)
        self.assertFalse(liquidation.is_editable)

        with self.assertRaises(ValidationError):
            resubmit_liquidation(
                liquidation,
                technician=self.technician,
                changes={"equipment_serial": "XYZ987"},
            )

        with self.assertRaises(ValidationError):
            request_liquidation_correction(
                liquidation,
                validator=self.validator,
                reason="Corrección tardía",
            )

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.equipment_serial, "ABC123")
        self.assertEqual(liquidation.review_status, ReviewStatus.VALIDATED)


class LiquidationReviewAtomicityTests(WorkOrderTestCase):
    """Transacciones y consistencia."""

    def test_failed_resubmission_reverts_every_change(self):
        """22. Una falla durante el reenvío revierte los cambios."""
        liquidation = self.create_liquidation_awaiting_correction()

        with self.assertRaises(ValidationError):
            resubmit_liquidation(
                liquidation,
                technician=self.technician,
                changes={
                    "equipment_serial": "XYZ987",
                    # Cantidad inválida: revienta después de haber escrito la
                    # liquidación, que es justo el escenario peligroso.
                    "items": [
                        {
                            "material_name": "Cable drop",
                            "quantity": 0,
                        },
                    ],
                },
            )

        liquidation.refresh_from_db()

        self.assertEqual(liquidation.equipment_serial, "ABC123")
        self.assertEqual(liquidation.correction_count, 0)
        self.assertIsNone(liquidation.resubmitted_at)
        self.assertEqual(
            liquidation.review_status,
            ReviewStatus.CORRECTION_REQUESTED,
        )
        self.assertFalse(
            WorkOrderLiquidationCorrection.objects.filter(
                liquidation=liquidation,
            ).exists()
        )

    def test_failed_validation_leaves_no_partial_validated_at(self):
        """23. Una falla durante la validación no deja validated_at parcial."""
        liquidation = self.create_submitted_liquidation()

        def explode(sender, instance, **kwargs):
            raise RuntimeError("Fallo simulado después de escribir")

        # El receptor corre dentro de la misma transacción que el save(), así
        # que la escritura ya ocurrió cuando revienta: si no hubiera atomicidad
        # quedaría validated_at grabado.
        post_save.connect(explode, sender=WorkOrderLiquidation)

        try:
            with self.assertRaises(RuntimeError):
                validate_liquidation(liquidation, validator=self.validator)
        finally:
            post_save.disconnect(explode, sender=WorkOrderLiquidation)

        liquidation.refresh_from_db()

        self.assertIsNone(liquidation.validated_at)
        self.assertIsNone(liquidation.validated_by)
        self.assertEqual(liquidation.review_status, ReviewStatus.SUBMITTED)


class LiquidationCorrectionTraceabilityTests(WorkOrderTestCase):
    """Trazabilidad de la única corrección."""

    def test_traceability_keeps_values_before_and_after(self):
        """24. La trazabilidad conserva los valores antes y después."""
        liquidation = self.create_liquidation_awaiting_correction(
            reason="Serie de ONU incorrecta",
        )

        resubmit_liquidation(
            liquidation,
            technician=self.technician,
            changes={"equipment_serial": "XYZ987"},
            remarks="Se corrigió la serie leyendo la etiqueta del equipo.",
        )

        correction = WorkOrderLiquidationCorrection.objects.get(
            liquidation=liquidation,
        )

        self.assertEqual(correction.values_before, {"equipment_serial": "ABC123"})
        self.assertEqual(correction.values_after, {"equipment_serial": "XYZ987"})
        self.assertEqual(correction.corrected_by, self.technician)
        self.assertEqual(correction.correction_reason, "Serie de ONU incorrecta")
        self.assertIsNotNone(correction.created_at)

        # El campo que no cambió no ensucia el snapshot.
        self.assertNotIn("network_port", correction.values_before)

        summary = correction.summary()

        self.assertIn("ANTES: equipment_serial=ABC123", summary)
        self.assertIn("MOTIVO: Serie de ONU incorrecta", summary)
        self.assertIn("DESPUÉS: equipment_serial=XYZ987", summary)
