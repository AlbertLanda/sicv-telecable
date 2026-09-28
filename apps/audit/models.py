from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """Acción autenticada registrada sin copiar datos sensibles del formulario."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_events",
        verbose_name="Usuario",
    )
    branch = models.ForeignKey(
        "organization.Branch",
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
        verbose_name="Sede",
    )
    method = models.CharField(max_length=10, verbose_name="Método")
    route_name = models.CharField(max_length=180, blank=True, verbose_name="Ruta lógica")
    path = models.CharField(max_length=500, verbose_name="Ruta")
    status_code = models.PositiveSmallIntegerField(default=200, verbose_name="Estado HTTP")
    description = models.CharField(max_length=240, verbose_name="Actividad")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha y hora")

    class Meta:
        verbose_name = "Evento de auditoría"
        verbose_name_plural = "Eventos de auditoría"
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["-created_at"], name="audit_event_created_idx"),
            models.Index(fields=["actor", "-created_at"], name="audit_actor_created_idx"),
            models.Index(fields=["branch", "-created_at"], name="audit_branch_created_idx"),
        ]

    def __str__(self):
        return f"{self.actor} · {self.description}"
