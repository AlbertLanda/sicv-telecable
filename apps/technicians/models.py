from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class TechnicianProfile(models.Model):
    """Clasificación operativa del personal técnico."""

    class Area(models.TextChoices):
        INTERNAL_NETWORK = "INTERNAL_NETWORK", "Red interna"
        PEX = "PEX", "Planta Externa"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="technician_profile",
        verbose_name="Técnico",
    )
    area = models.CharField(
        max_length=30,
        choices=Area.choices,
        default=Area.INTERNAL_NETWORK,
        verbose_name="Cuadrilla / especialidad",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Perfil técnico"
        verbose_name_plural = "Perfiles técnicos"

    def clean(self):
        super().clean()
        from apps.accounts.models import User

        if self.user_id and self.user.role != User.Role.TECHNICIAN:
            raise ValidationError({
                "user": "El perfil técnico solo corresponde a usuarios Técnico."
            })

    def __str__(self):
        return f"{self.user} - {self.get_area_display()}"
