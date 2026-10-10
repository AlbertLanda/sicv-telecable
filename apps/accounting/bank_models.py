from django.conf import settings
from django.db import models
from django.db.models import Q


class BankAccount(models.Model):
    issuer = models.ForeignKey("payments.Issuer", on_delete=models.PROTECT)
    bank = models.CharField(max_length=80)
    number = models.CharField(max_length=40)
    currency = models.CharField(max_length=3, default="PEN")
    label = models.CharField(max_length=120)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["bank", "number"]
        default_permissions = ()
        permissions = [("view_bank", "Consultar conciliación bancaria por empresa"),
                       ("manage_bank_accounts", "Configurar cuentas bancarias"),
                       ("import_bank", "Importar extractos bancarios"),
                       ("reconcile_bank", "Confirmar y deshacer conciliaciones bancarias")]
        constraints = [models.UniqueConstraint(fields=["bank", "number", "currency"], name="bank_account_identity_unique"),
                       models.CheckConstraint(condition=Q(currency="PEN"), name="bank_account_pen_only")]

    def __str__(self):
        return f"{self.bank} · {self.label} · {self.number} · {self.issuer.code}"


class BankLine(models.Model):
    account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="lines")
    external_id = models.CharField(max_length=120)
    date = models.DateField()
    operation = models.CharField(max_length=120)
    operation_key = models.CharField(max_length=120, db_index=True)
    description = models.CharField(max_length=500, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    fingerprint = models.CharField(max_length=64)

    class Meta:
        ordering = ["date", "pk"]
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["account", "external_id"], name="bank_external_id_unique"),
                       models.CheckConstraint(condition=~Q(amount=0), name="bank_line_nonzero")]


class BankStatement(models.Model):
    account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="statements")
    filename = models.CharField(max_length=180)
    sha256 = models.CharField(max_length=64)
    original = models.BinaryField(editable=False)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    imported_at = models.DateTimeField(auto_now_add=True)
    lines = models.ManyToManyField(BankLine, related_name="statements")
    row_count = models.PositiveIntegerField()
    new_count = models.PositiveIntegerField()

    class Meta:
        ordering = ["-pk"]
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["account", "sha256"], name="bank_statement_hash_unique")]


class BankMatch(models.Model):
    line = models.ForeignKey(BankLine, on_delete=models.PROTECT, related_name="matches")
    payment = models.ForeignKey("payments.Payment", on_delete=models.PROTECT, null=True, blank=True, related_name="bank_matches")
    cash_entry = models.ForeignKey("payments.CashEntry", on_delete=models.PROTECT, null=True, blank=True, related_name="bank_matches")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bank_confirmations")
    confirmed_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=500)
    snapshot = models.JSONField()
    active = models.BooleanField(default=True)
    released_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="bank_releases")
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-pk"]
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=Q(payment__isnull=False, cash_entry__isnull=True) | Q(payment__isnull=True, cash_entry__isnull=False), name="bank_match_one_target"),
            models.UniqueConstraint(fields=["line"], condition=Q(active=True), name="bank_line_one_active_match"),
            models.UniqueConstraint(fields=["payment"], condition=Q(active=True, payment__isnull=False), name="bank_payment_one_active_match"),
            models.UniqueConstraint(fields=["cash_entry"], condition=Q(active=True, cash_entry__isnull=False), name="bank_deposit_one_active_match"),
            models.CheckConstraint(condition=Q(active=True, released_by__isnull=True, released_at__isnull=True) | Q(active=False, released_by__isnull=False, released_at__isnull=False), name="bank_release_complete"),
        ]


class BankEvent(models.Model):
    account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="events")
    line = models.ForeignKey(BankLine, on_delete=models.PROTECT, null=True, blank=True, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=30)
    note = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-pk"]
        default_permissions = ()
