from django.conf import settings
from django.db import models
from django.db.models import Q


class DebtAdjustment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente de aprobación"
        APPROVED = "APPROVED", "Aprobado"
        REJECTED = "REJECTED", "Rechazado"

    charge = models.ForeignKey("payments.Charge", on_delete=models.PROTECT, related_name="adjustments")
    # Positivo reduce deuda; negativo restituye un crédito aprobado.
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=500)
    reference = models.CharField(max_length=120)
    reversal_of = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversals")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="debt_requests")
    requested_at = models.DateTimeField(auto_now_add=True)
    request_key = models.UUIDField(unique=True)
    fingerprint = models.CharField(max_length=64)
    expected_state = models.CharField(max_length=64)
    request_snapshot = models.JSONField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="debt_reviews")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)
    result_snapshot = models.JSONField(default=dict)

    class Meta:
        ordering = ["-pk"]
        default_permissions = ()
        permissions = [("request_debt_adjustment", "Solicitar ajustes comerciales de deuda"),
                       ("review_debt_adjustment", "Revisar ajustes de deuda en sus sedes")]
        constraints = [
            models.UniqueConstraint(fields=["charge"], condition=Q(status="PENDING"), name="debt_one_pending_per_charge"),
            models.UniqueConstraint(fields=["reversal_of"], condition=Q(status__in=["PENDING", "APPROVED"]), name="debt_reversal_once"),
            models.CheckConstraint(condition=Q(amount__gt=0, reversal_of__isnull=True) | Q(amount__lt=0, reversal_of__isnull=False), name="debt_adjustment_sign"),
            models.CheckConstraint(condition=Q(status="PENDING", reviewed_by__isnull=True, reviewed_at__isnull=True) | Q(status__in=["APPROVED", "REJECTED"], reviewed_by__isnull=False, reviewed_at__isnull=False), name="debt_review_complete"),
            models.CheckConstraint(condition=Q(reviewed_by__isnull=True) | ~Q(reviewed_by=models.F("requested_by")), name="debt_no_self_review"),
        ]

    @property
    def kind_label(self):
        return "Restitución de ajuste" if self.reversal_of_id else "Reducción de deuda"
