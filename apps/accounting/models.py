"""Evidence imported for reconciliation; never changes fiscal or collection records."""
from django.conf import settings
from django.db import models


class CompanyAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    issuer = models.ForeignKey("payments.Issuer", on_delete=models.PROTECT)
    enabled = models.BooleanField(default=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="accounting_access_changes")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "issuer"], name="accounting_user_issuer_unique")]
        default_permissions = ()
        permissions = [("manage_access", "Administrar acceso contable por empresa")]


class ImportBatch(models.Model):
    class Source(models.TextChoices):
        OSIPTEL = "OSIPTEL", "SICV antiguo · OSIPTEL"
        RVIE = "RVIE", "SIRE · archivo de comparación"

    issuer = models.ForeignKey("payments.Issuer", on_delete=models.PROTECT)
    issuer_ruc = models.CharField(max_length=11)
    period = models.DateField(help_text="Primer día del periodo tributario seleccionado")
    source = models.CharField(max_length=10, choices=Source.choices)
    filename = models.CharField(max_length=200)
    sha256 = models.CharField(max_length=64)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    document_count = models.PositiveIntegerField()
    line_count = models.PositiveIntegerField()
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at", "-pk"]
        default_permissions = ()
        permissions = [("view_workspace", "Consultar conciliación contable"),
                       ("import_reports", "Importar reportes para conciliación"),
                       ("review_documents", "Anotar y clasificar evidencia contable")]
        constraints = [models.UniqueConstraint(fields=["issuer", "period", "source", "sha256"], name="accounting_import_unique")]
        indexes = [models.Index(fields=["issuer", "period", "source"], name="accounting_period_source_idx")]


class Document(models.Model):
    batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="documents")
    document_type = models.CharField(max_length=2)
    series = models.CharField(max_length=20)
    number = models.CharField(max_length=20)
    issue_date = models.DateField()
    receiver_document = models.CharField(max_length=20, blank=True)
    receiver_name = models.CharField(max_length=250, blank=True)
    currency = models.CharField(max_length=3, default="PEN")
    base = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    tax = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    total = models.DecimalField(max_digits=18, decimal_places=2)
    local_state = models.CharField(max_length=60, blank=True)
    sunat_state = models.CharField(max_length=60, blank=True)
    sire_state = models.CharField(max_length=60, blank=True)
    source_details = models.JSONField(default=dict)
    flags = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "document_type", "series", "number"], name="accounting_document_unique")]
        ordering = ["issue_date", "document_type", "series", "number", "pk"]
        default_permissions = ()

    @property
    def key(self):
        return self.document_type, self.series, self.number

    @property
    def label(self):
        return f"{self.document_type} · {self.series}-{self.number}"


class Line(models.Model):
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="lines")
    source_row = models.PositiveIntegerField()
    description = models.CharField(max_length=1000, blank=True)
    concept = models.CharField(max_length=160, blank=True)
    technology = models.CharField(max_length=100, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=5)
    base = models.DecimalField(max_digits=18, decimal_places=2)
    tax = models.DecimalField(max_digits=18, decimal_places=2)
    total = models.DecimalField(max_digits=18, decimal_places=2)
    flags = models.JSONField(default=list)

    class Meta:
        ordering = ["source_row", "pk"]
        constraints = [models.UniqueConstraint(fields=["document", "source_row"], name="accounting_line_row_unique")]
        default_permissions = ()


class Review(models.Model):
    """Append-only observations; the imported amounts and states stay unchanged."""
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="reviews")
    line = models.ForeignKey(Line, on_delete=models.PROTECT, null=True, blank=True, related_name="reviews")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    note = models.TextField(max_length=2000)
    concept = models.CharField(max_length=160, blank=True)
    technology = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        default_permissions = ()
