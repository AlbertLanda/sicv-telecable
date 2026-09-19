"""Catálogo operativo de cajas NAP disponibles por sede."""

from django.db import models

from apps.organization.models import Branch


class NetworkAccessPoint(models.Model):
    """Caja NAP seleccionable por los técnicos durante la atención de campo.

    `legacy_id` conserva la referencia del SICV anterior para poder auditar o
    repetir migraciones sin depender del texto visible. `code` es el código de
    conexión que aparece al final del nombre legado y es el término principal
    de búsqueda desde el celular.
    """

    legacy_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        unique=True,
        verbose_name="ID sistema anterior",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="network_access_points",
        verbose_name="Sede",
    )
    code = models.CharField(
        max_length=40,
        verbose_name="Código NAP",
    )
    name = models.CharField(
        max_length=220,
        verbose_name="Nombre NAP",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "work_orders"
        verbose_name = "NAP"
        verbose_name_plural = "NAP"
        ordering = ["branch", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "code"],
                name="unique_nap_code_per_branch",
            ),
        ]
        indexes = [
            models.Index(fields=["branch", "is_active"], name="nap_branch_active_idx"),
            models.Index(fields=["code"], name="nap_code_idx"),
        ]

    def __str__(self):
        return self.name
