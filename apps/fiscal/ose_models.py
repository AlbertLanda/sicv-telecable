"""Configuración de conexión y evidencia de pruebas, separadas de los CPE."""
import re
import uuid
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class OseConnection(models.Model):
    class Mode(models.TextChoices):
        DISABLED = "DISABLED", "Deshabilitado"
        SIMULATOR = "SIMULATOR", "Simulador local de pruebas"
        PENDING = "PENDING", "Proveedor pendiente de integrar"

    issuer = models.OneToOneField("payments.Issuer", on_delete=models.PROTECT, related_name="ose_connection")
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.DISABLED)
    provider_name = models.CharField(max_length=120, blank=True, verbose_name="Proveedor previsto")
    test_endpoint = models.URLField(blank=True, verbose_name="URL del servicio de pruebas")
    production_endpoint = models.URLField(blank=True, verbose_name="URL del servicio de producción")
    username_setting = models.CharField(max_length=100, blank=True, verbose_name="Variable para el usuario")
    password_setting = models.CharField(max_length=100, blank=True, verbose_name="Variable para la clave")
    certificate_setting = models.CharField(max_length=100, blank=True, verbose_name="Variable para el certificado")
    certificate_password_setting = models.CharField(max_length=100, blank=True, verbose_name="Variable para la clave del certificado")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Conexión OSE prevista"
        verbose_name_plural = "Conexiones OSE previstas"
        permissions = [("configure_ose", "Puede configurar la conexión OSE prevista"),
                       ("simulate_ose", "Puede ejecutar pruebas simuladas de OSE")]
        constraints = [models.CheckConstraint(condition=Q(mode__in=["DISABLED", "SIMULATOR", "PENDING"]), name="ose_connection_mode_valid")]

    def clean(self):
        super().clean()
        errors = {}
        for field in ("test_endpoint", "production_endpoint"):
            value = getattr(self, field)
            if value:
                try:
                    url = urlsplit(value)
                    valid = url.scheme == "https" and url.hostname and not (url.username or url.password or url.query or url.fragment)
                except ValueError:
                    valid = False
                if not valid:
                    errors[field] = "Use una URL HTTPS sin credenciales, parámetros ni fragmentos."
        for field in ("username_setting", "password_setting", "certificate_setting", "certificate_password_setting"):
            value = getattr(self, field)
            if value and not re.fullmatch(r"SICV_OSE_[A-Z0-9_]+", value):
                errors[field] = "Indique el nombre de una variable SICV_OSE_…; no pegue claves o certificados."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.issuer} · {self.get_mode_display()}"


class OseConnectionRevision(models.Model):
    connection = models.ForeignKey(OseConnection, on_delete=models.PROTECT, related_name="revisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    snapshot = models.JSONField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class OseSimulation(models.Model):
    class Scenario(models.TextChoices):
        ACCEPTED = "ACCEPTED", "Aceptación simulada"
        OBSERVED = "OBSERVED", "Aceptación con observación simulada"
        REJECTED = "REJECTED", "Rechazo simulado"
        DELAYED = "DELAYED", "Respuesta pendiente y consulta posterior"
        LOST_REPLY = "LOST_REPLY", "Recepción simulada con respuesta perdida"
        NOT_SENT = "NOT_SENT", "Falla temporal antes de recibir el envío"

    class State(models.TextChoices):
        READY = "READY", "Prueba preparada"
        WORKING = "WORKING", "Prueba en ejecución"
        PROCESSING = "PROCESSING", "Prueba pendiente de consulta"
        UNCERTAIN = "UNCERTAIN", "Prueba con resultado desconocido: consultar"
        RETRYABLE = "RETRYABLE", "Prueba sin envío recibido: reintentar"
        ACCEPTED = "ACCEPTED", "Aceptación simulada · sin validez tributaria"
        OBSERVED = "OBSERVED", "Observación simulada · sin validez tributaria"
        REJECTED = "REJECTED", "Rechazo simulado · sin efecto fiscal"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    document = models.ForeignKey("fiscal.FiscalDocument", on_delete=models.PROTECT, related_name="ose_simulations")
    request_key = models.UUIDField(unique=True, editable=False)
    request_fingerprint = models.CharField(max_length=64, editable=False)
    scenario = models.CharField(max_length=20, choices=Scenario.choices)
    connection_snapshot = models.JSONField(editable=False)
    payload = models.JSONField(editable=False)
    payload_hash = models.CharField(max_length=64, editable=False)
    state = models.CharField(max_length=20, choices=State.choices, default=State.READY)
    ticket = models.CharField(max_length=100, blank=True)
    response = models.JSONField(default=dict, blank=True)
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_until = models.DateTimeField(null=True, blank=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Prueba simulada OSE"
        verbose_name_plural = "Pruebas simuladas OSE"
        constraints = [
            models.CheckConstraint(condition=Q(scenario__in=["ACCEPTED", "OBSERVED", "REJECTED", "DELAYED", "LOST_REPLY", "NOT_SENT"]), name="ose_simulation_scenario_valid"),
            models.CheckConstraint(condition=Q(state__in=["READY", "WORKING", "PROCESSING", "UNCERTAIN", "RETRYABLE", "ACCEPTED", "OBSERVED", "REJECTED"]), name="ose_simulation_state_valid"),
            models.CheckConstraint(condition=(Q(state="WORKING", lease_token__isnull=False, lease_until__isnull=False)
                | (~Q(state="WORKING") & Q(lease_token__isnull=True, lease_until__isnull=True))), name="ose_simulation_lease_consistent"),
        ]

    @property
    def is_terminal(self):
        return self.state in (self.State.ACCEPTED, self.State.OBSERVED, self.State.REJECTED)

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            mutable = {"state", "ticket", "response", "lease_token", "lease_until"}
            for field in self._meta.concrete_fields:
                if field.name not in mutable and getattr(self, field.attname) != getattr(old, field.attname):
                    raise ValidationError("La solicitud de prueba está congelada; prepare otra prueba.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Conserve el historial de la prueba.")


class OseSimulationAttempt(models.Model):
    class Operation(models.TextChoices):
        SUBMIT = "SUBMIT", "Envío simulado"
        QUERY = "QUERY", "Consulta simulada"

    simulation = models.ForeignKey(OseSimulation, on_delete=models.PROTECT, related_name="attempts")
    number = models.PositiveIntegerField()
    token = models.UUIDField(unique=True, editable=False)
    operation = models.CharField(max_length=10, choices=Operation.choices)
    outcome = models.CharField(max_length=20, default="RUNNING", choices=[("RUNNING", "En ejecución"), ("DONE", "Finalizado"), ("FAILED", "Sin respuesta concluyente"), ("ABANDONED", "Ejecución interrumpida")])
    response = models.JSONField(default=dict, blank=True)
    message = models.CharField(max_length=200, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["number"]
        constraints = [models.UniqueConstraint(fields=["simulation", "number"], name="ose_simulation_attempt_unique")]


class OseSimulatorReceipt(models.Model):
    """Buzón del proveedor ficticio. No representa un CDR ni un documento fiscal."""
    request_id = models.UUIDField(unique=True)
    payload_hash = models.CharField(max_length=64)
    result = models.CharField(max_length=20)
    ticket = models.CharField(max_length=100)
    pending_queries = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class OseSimulationEvent(models.Model):
    simulation = models.ForeignKey(OseSimulation, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=20, choices=[("CREATED", "Prueba preparada"), ("STARTED", "Intento iniciado"), ("FINISHED", "Intento finalizado"), ("RECOVERED", "Ejecución interrumpida recuperada")])
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    message = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
