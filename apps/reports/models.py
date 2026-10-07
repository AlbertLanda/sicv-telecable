from django.conf import settings
from django.db import models


class AccountingReviewNote(models.Model):
    """Cada envío conserva una revisión; no modifica operaciones del ERP."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente de revisar"
        REVIEWED = "REVIEWED", "Revisado sin observaciones"
        CHANGES = "CHANGES", "Falta dato o ajuste"
        NOT_APPLICABLE = "NOT_APPLICABLE", "No aplica (explicar)"

    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                 related_name="accounting_review_notes")
    catalog_version = models.PositiveSmallIntegerField()
    case_code = models.CharField(max_length=32)
    status = models.CharField(max_length=20, choices=Status.choices)
    missing_data = models.CharField(max_length=500, blank=True)
    note = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["reviewer", "catalog_version", "case_code"],
                                name="review_user_version_case")]
        constraints = [models.CheckConstraint(
            condition=models.Q(status__in=["PENDING", "REVIEWED", "CHANGES", "NOT_APPLICABLE"]),
            name="accounting_review_valid_status",
        )]
