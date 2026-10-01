"""Preparación fiscal independiente de deuda, pagos y talonarios internos.

Esta primera entrega solo conserva borradores para revisión. No representa
CPE aceptados, no firma XML y no reserva correlativos oficiales.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class DocumentType(models.TextChoices):
    INVOICE = "01", "Factura"
    SALES_RECEIPT = "03", "Boleta de venta"
    PUBLIC_SERVICE = "14", "Recibo de servicios públicos"


class FiscalProfile(models.Model):
    class Modality(models.TextChoices):
        PENDING = "PENDING", "Por confirmar"
        CONTRIBUTOR = "CONTRIBUTOR", "SEE del contribuyente"
        SFS = "SFS", "Facturador SUNAT"
        OSE = "OSE", "SEE OSE"

    class Trigger(models.TextChoices):
        PENDING = "PENDING", "Por confirmar"
        MONTHLY = "MONTHLY", "Al generar la mensualidad"
        PAYMENT = "PAYMENT", "Al registrar el cobro"
        OTHER = "OTHER", "Otra regla documentada"

    issuer = models.OneToOneField(
        "payments.Issuer", on_delete=models.PROTECT, related_name="fiscal_profile",
        verbose_name="Empresa emisora",
    )
    modality = models.CharField(
        max_length=20, choices=Modality.choices, default=Modality.PENDING,
        verbose_name="Modalidad de emisión",
    )
    provider_name = models.CharField(
        max_length=120, blank=True, verbose_name="Proveedor o herramienta",
        help_text="Nombre solamente. No guardar claves ni certificados aquí.",
    )
    document_types = models.JSONField(default=list, blank=True, verbose_name="Documentos previstos")
    billing_trigger = models.CharField(
        max_length=20, choices=Trigger.choices, default=Trigger.PENDING,
        verbose_name="Momento de emisión",
    )
    tax_rules_confirmed = models.BooleanField(default=False, verbose_name="Tratamiento tributario confirmado")
    receiver_rules_confirmed = models.BooleanField(default=False, verbose_name="Reglas del receptor confirmadas")
    confirmation_reference = models.TextField(
        blank=True, verbose_name="Referencia de la validación contable",
        help_text="Decisiones y fecha de confirmación. Esta referencia no habilita la emisión.",
    )
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración fiscal"
        verbose_name_plural = "Configuraciones fiscales"

    def __str__(self):
        return str(self.issuer)

    def clean(self):
        super().clean()
        if not isinstance(self.document_types, list) or any(
            item not in DocumentType.values for item in self.document_types
        ) or len(set(self.document_types)) != len(self.document_types):
            raise ValidationError({"document_types": "Seleccione tipos de documento válidos sin repetir."})
        if (self.tax_rules_confirmed or self.receiver_rules_confirmed) and not self.confirmation_reference.strip():
            raise ValidationError({"confirmation_reference": "Indique la referencia de la confirmación."})

    @property
    def pending_decisions(self):
        pending = []
        if self.modality == self.Modality.PENDING:
            pending.append("Modalidad de emisión por empresa")
        if not self.document_types:
            pending.append("Tipos de documento utilizados")
        if self.billing_trigger == self.Trigger.PENDING:
            pending.append("Momento de emisión")
        if not self.tax_rules_confirmed:
            pending.append("Tratamiento tributario de los conceptos y descuentos")
        if not self.receiver_rules_confirmed:
            pending.append("Identidad y domicilio del receptor fiscal")
        return pending


class FiscalProfileRevision(models.Model):
    profile = models.ForeignKey(FiscalProfile, on_delete=models.PROTECT, related_name="revisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    snapshot = models.JSONField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Revisión de configuración fiscal"
        verbose_name_plural = "Revisiones de configuración fiscal"


class FiscalDocument(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Borrador para revisión"
        CANCELLED = "CANCELLED", "Borrador descartado"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    request_key = models.UUIDField(unique=True, editable=False)
    request_fingerprint = models.CharField(max_length=64, editable=False)
    issuer = models.ForeignKey("payments.Issuer", on_delete=models.PROTECT, related_name="fiscal_drafts")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="fiscal_drafts")
    branch = models.ForeignKey("organization.Branch", on_delete=models.PROTECT)
    document_type = models.CharField(max_length=2, choices=DocumentType.choices)
    proposed_issue_date = models.DateField(default=timezone.localdate)
    currency = models.CharField(max_length=3)
    source_total = models.DecimalField(max_digits=12, decimal_places=2)
    snapshot = models.JSONField(editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="fiscal_drafts")
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="cancelled_fiscal_drafts",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)

    class Meta:
        verbose_name = "Borrador de facturación"
        verbose_name_plural = "Borradores de facturación"
        ordering = ["-created_at", "-pk"]
        permissions = [("cancel_fiscaldocument", "Puede descartar borradores de facturación")]
        constraints = [
            models.CheckConstraint(condition=Q(source_total__gt=0), name="fiscal_positive_source_total"),
            models.CheckConstraint(
                condition=(Q(status="DRAFT", cancelled_at__isnull=True, cancelled_by__isnull=True, cancel_reason="")
                           | (Q(status="CANCELLED", cancelled_at__isnull=False, cancelled_by__isnull=False)
                              & ~Q(cancel_reason=""))),
                name="fiscal_draft_state_consistent",
            ),
        ]

    def __str__(self):
        return f"BORRADOR {self.public_id}"

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            # La corrección es descartar y preparar otra versión, nunca
            # reescribir la evidencia que Contabilidad estaba revisando.
            mutable = {"status", "cancelled_by", "cancelled_at", "cancel_reason"}
            for field in self._meta.concrete_fields:
                if field.name not in mutable and getattr(self, field.attname) != getattr(original, field.attname):
                    raise ValidationError("El contenido del borrador está congelado; prepare uno nuevo.")
            if original.status == self.Status.CANCELLED:
                raise ValidationError("Un borrador descartado no puede modificarse.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Conserve la evidencia: descarte el borrador con un motivo.")


class FiscalEvent(models.Model):
    document = models.ForeignKey(FiscalDocument, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=20, choices=[("CREATED", "Preparado"), ("CANCELLED", "Descartado")])
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "Evento de preparación fiscal"
        verbose_name_plural = "Eventos de preparación fiscal"
