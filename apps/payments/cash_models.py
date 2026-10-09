"""Caja física en PEN. Los movimientos y las versiones del cierre se conservan."""

from django.conf import settings
from django.db import models
from django.db.models import Q


class CashSession(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierta"
        SUBMITTED = "SUBMITTED", "En revisión"
        APPROVED = "APPROVED", "Aprobada"

    office = models.ForeignKey("organization.Office", on_delete=models.PROTECT)
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    business_date = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    opening_amount = models.DecimalField(max_digits=14, decimal_places=2)
    opening_reason = models.CharField(max_length=300)
    previous = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="following")
    opened_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-business_date", "-pk"]
        permissions = [
            ("operate_cash", "Puede operar su caja en oficinas autorizadas"),
            ("review_cash", "Puede revisar y aprobar cajas de sus oficinas"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["office", "cashier", "business_date"], name="cash_session_day_unique"),
            models.UniqueConstraint(fields=["office", "cashier"], condition=~Q(status="APPROVED"), name="cash_session_active_unique"),
            models.CheckConstraint(condition=Q(opening_amount__gte=0), name="cash_opening_nonnegative"),
            models.CheckConstraint(condition=Q(status__in=["OPEN", "SUBMITTED", "APPROVED"]), name="cash_session_valid_status"),
        ]


class CashEntry(models.Model):
    class Kind(models.TextChoices):
        PAYMENT = "PAYMENT", "Cobro"
        VOID = "VOID", "Anulación de cobro"
        EXPENSE = "EXPENSE", "Gasto en efectivo"
        DEPOSIT = "DEPOSIT", "Depósito de caja al banco"
        INCOME = "INCOME", "Otro ingreso en efectivo"
        GUARANTEE = "GUARANTEE", "Garantía recibida en efectivo"
        REVERSAL = "REVERSAL", "Reversión de movimiento"

    session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="entries")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=20)
    issuer = models.ForeignKey("payments.Issuer", on_delete=models.PROTECT, null=True, blank=True)
    issuer_label = models.CharField(max_length=150, blank=True)
    issuer_ruc = models.CharField(max_length=11, blank=True)
    payment = models.ForeignKey("payments.Payment", on_delete=models.PROTECT, null=True, blank=True)
    reversal_of = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversal")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    description = models.CharField(max_length=300)
    reference = models.CharField(max_length=100, blank=True)
    bank = models.CharField(max_length=100, blank=True)
    account = models.CharField(max_length=100, blank=True)
    document_type = models.CharField(max_length=50, blank=True)
    document_number = models.CharField(max_length=100, blank=True)
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.UUIDField(unique=True, null=True, blank=True, editable=False)
    fingerprint = models.CharField(max_length=64, blank=True, editable=False)
    # Detecta reenvíos de un depósito, incluso entre oficinas/cajeros.
    deposit_key = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["payment", "kind"], condition=Q(payment__isnull=False), name="cash_payment_kind_unique"),
            models.CheckConstraint(condition=~Q(amount=0), name="cash_entry_nonzero"),
        ]


class CashClose(models.Model):
    """Una versión enviada es inmutable; la decisión se añade como CashEvent."""
    session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="closes")
    revision = models.PositiveIntegerField()
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    submitted_at = models.DateTimeField(auto_now_add=True)
    expected_cash = models.DecimalField(max_digits=14, decimal_places=2)
    declared_cash = models.DecimalField(max_digits=14, decimal_places=2)
    difference = models.DecimalField(max_digits=14, decimal_places=2)
    explanation = models.CharField(max_length=500, blank=True)
    snapshot = models.JSONField()
    digest = models.CharField(max_length=64)

    class Meta:
        ordering = ["-revision"]
        constraints = [models.UniqueConstraint(fields=["session", "revision"], name="cash_close_revision_unique")]


class CashEvent(models.Model):
    ACTION_LABELS = {
        "OPENED": "Apertura", "MOVEMENT": "Movimiento registrado", "REVERSED": "Reversión",
        "SUBMITTED": "Cierre enviado", "APPROVED": "Cierre aprobado", "RETURNED": "Devuelto para corrección",
    }
    session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="events")
    close = models.ForeignKey(CashClose, on_delete=models.PROTECT, null=True, blank=True, related_name="events")
    action = models.CharField(max_length=20)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]

    def get_action_display(self):
        return self.ACTION_LABELS.get(self.action, self.action)
