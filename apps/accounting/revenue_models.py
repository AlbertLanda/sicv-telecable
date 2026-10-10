from django.conf import settings
from django.db import models
from django.db.models import Q


class RevenueRule(models.Model):
    """Versiones de una alerta administrativa, sin efecto sobre los cobros."""
    class Period(models.TextChoices):
        DAY = "DAY", "Diario"
        FORTNIGHT = "FORTNIGHT", "Quincenal"
        MONTH = "MONTH", "Mensual"
        YEAR = "YEAR", "Anual"

    issuer = models.ForeignKey("payments.Issuer", on_delete=models.PROTECT)
    issuer_ruc = models.CharField(max_length=11)
    period = models.CharField(max_length=10, choices=Period.choices)
    revision = models.PositiveIntegerField()
    enabled = models.BooleanField(default=True)
    limit = models.DecimalField(max_digits=16, decimal_places=2)
    warning_percent = models.PositiveSmallIntegerField(default=80)
    reason = models.CharField(max_length=500)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.UUIDField(unique=True)
    fingerprint = models.CharField(max_length=64)

    class Meta:
        ordering = ["-pk"]
        default_permissions = ()
        permissions = [("view_revenue", "Consultar recaudación por empresa"),
                       ("manage_revenue_rules", "Configurar alertas administrativas de recaudación")]
        constraints = [
            models.UniqueConstraint(fields=["issuer", "period", "revision"], name="revenue_rule_revision_unique"),
            models.CheckConstraint(condition=Q(limit__gt=0), name="revenue_rule_positive_limit"),
            models.CheckConstraint(condition=Q(warning_percent__gte=1, warning_percent__lte=100), name="revenue_rule_warning_range"),
            models.CheckConstraint(condition=Q(period__in=["DAY", "FORTNIGHT", "MONTH", "YEAR"]), name="revenue_rule_valid_period"),
        ]
