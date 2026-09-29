from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class LegacyRecord(models.Model):
    """Rastro inmutable de un registro recuperado del sistema anterior.

    `raw_payload` conserva exactamente lo recibido desde SICAV. La
    interpretación que use SICV vive en `normalized_payload` y sí puede ser
    corregida, pero cada cambio queda registrado en LegacyRecordCorrection.
    """

    class Source(models.TextChoices):
        SICAV = "SICAV", "SICAV"

    class EntityType(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Abonado"
        ADDRESS = "ADDRESS", "Dirección"
        SUBSCRIPTION = "SUBSCRIPTION", "Suscripción"
        CONTRACT = "CONTRACT", "Contrato"
        PLAN_HISTORY = "PLAN_HISTORY", "Historial de plan"
        WORK_ORDER = "WORK_ORDER", "Orden de trabajo"
        CHARGE = "CHARGE", "Cargo / deuda"
        PAYMENT = "PAYMENT", "Pago"
        RECEIPT = "RECEIPT", "Comprobante"
        EVIDENCE = "EVIDENCE", "Evidencia"
        EQUIPMENT = "EQUIPMENT", "Equipo"
        AUDIT_EVENT = "AUDIT_EVENT", "Auditoría"

    class ReviewStatus(models.TextChoices):
        IMPORTED = "IMPORTED", "Importado"
        REVIEW = "REVIEW", "Por revisar"
        VALIDATED = "VALIDATED", "Validado"
        CORRECTED = "CORRECTED", "Corregido"

    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.SICAV,
        verbose_name="Origen",
    )
    entity_type = models.CharField(
        max_length=30,
        choices=EntityType.choices,
        verbose_name="Tipo de registro",
    )
    legacy_id = models.CharField(
        max_length=120,
        verbose_name="ID en sistema anterior",
    )

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="legacy_records",
        null=True,
        blank=True,
        verbose_name="Abonado SICV",
    )
    subscription = models.ForeignKey(
        "services.Subscription",
        on_delete=models.PROTECT,
        related_name="legacy_records",
        null=True,
        blank=True,
        verbose_name="Suscripción SICV",
    )

    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="legacy_records",
        verbose_name="Tipo de objeto normalizado",
    )
    target_object_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        verbose_name="ID de objeto normalizado",
    )
    target_object = GenericForeignKey(
        "target_content_type",
        "target_object_id",
    )

    raw_payload = models.JSONField(
        default=dict,
        verbose_name="Payload original",
        help_text="Copia inmutable del dato recuperado de SICAV.",
    )
    normalized_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Interpretación normalizada",
        help_text=(
            "Representación editable usada para revisar o corregir el mapeo "
            "sin modificar el dato original."
        ),
    )

    review_status = models.CharField(
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.IMPORTED,
        verbose_name="Estado de revisión",
    )
    review_notes = models.TextField(
        blank=True,
        verbose_name="Notas de revisión",
    )

    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legacy_records_imported",
        null=True,
        blank=True,
        verbose_name="Importado por",
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legacy_records_validated",
        null=True,
        blank=True,
        verbose_name="Validado por",
    )
    validated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Validado el",
    )
    imported_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Importado el",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Actualizado el",
    )

    class Meta:
        verbose_name = "Registro legacy"
        verbose_name_plural = "Registros legacy"
        ordering = ["entity_type", "legacy_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "entity_type", "legacy_id"],
                name="legacy_unique_source_entity_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["source", "entity_type", "legacy_id"],
                name="legacy_source_entity_idx",
            ),
            models.Index(
                fields=["review_status"],
                name="legacy_review_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.source} · {self.get_entity_type_display()} · {self.legacy_id}"

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values_list(
                "raw_payload",
                flat=True,
            ).first()
            if original is not None and original != self.raw_payload:
                raise ValidationError({
                    "raw_payload": (
                        "El payload original de un registro legacy es "
                        "inmutable. Corrija la interpretación normalizada."
                    )
                })
        return super().save(*args, **kwargs)

    @transaction.atomic
    def apply_normalized_correction(self, new_payload, *, user=None, reason=""):
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError({
                "reason": "Indique el motivo de la corrección."
            })

        previous = self.normalized_payload
        if previous == new_payload:
            return None

        correction = LegacyRecordCorrection.objects.create(
            record=self,
            previous_payload=previous,
            new_payload=new_payload,
            reason=reason,
            corrected_by=user,
        )
        self.normalized_payload = new_payload
        self.review_status = self.ReviewStatus.CORRECTED
        self.save(update_fields=[
            "normalized_payload",
            "review_status",
            "updated_at",
        ])
        return correction

    def mark_validated(self, *, user=None, notes=""):
        self.review_status = self.ReviewStatus.VALIDATED
        self.validated_by = user
        self.validated_at = timezone.now()
        if notes:
            self.review_notes = notes
        self.save(update_fields=[
            "review_status",
            "validated_by",
            "validated_at",
            "review_notes",
            "updated_at",
        ])


class LegacyRecordCorrection(models.Model):
    """Auditoría de una corrección hecha sobre la interpretación legacy."""

    record = models.ForeignKey(
        LegacyRecord,
        on_delete=models.CASCADE,
        related_name="corrections",
        verbose_name="Registro legacy",
    )
    previous_payload = models.JSONField(
        default=dict,
        verbose_name="Valor anterior",
    )
    new_payload = models.JSONField(
        default=dict,
        verbose_name="Valor nuevo",
    )
    reason = models.TextField(
        verbose_name="Motivo de la corrección",
    )
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legacy_record_corrections",
        null=True,
        blank=True,
        verbose_name="Corregido por",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de corrección",
    )

    class Meta:
        verbose_name = "Corrección legacy"
        verbose_name_plural = "Correcciones legacy"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"Corrección {self.record} · {self.created_at:%Y-%m-%d %H:%M}"
