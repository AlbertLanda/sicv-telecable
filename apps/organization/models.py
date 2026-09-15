from django.db import models


class Branch(models.Model):
    code = models.CharField(
        max_length=10,
        unique=True,
        verbose_name="Código"
    )

    name = models.CharField(
        max_length=100,
        verbose_name="Sede"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Sede"
        verbose_name_plural = "Sedes"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Office(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="offices",
        verbose_name="Sede"
    )

    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Código"
    )

    name = models.CharField(
        max_length=100,
        verbose_name="Oficina"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )

    # El deposito de la sede no es una ventanilla: nadie esta parado ahi. Es
    # donde cae lo que llega por banco -transferencia, deposito, billetera-,
    # que si entra en una sede concreta pero no lo recibe nadie en mostrador.
    #
    # Se marca en vez de reconocerse por el nombre porque de ese hecho
    # dependen dos cosas: no se ofrece como oficina desde la que se atiende,
    # y no puede ser la que el sistema elige sola para un operador que no
    # tiene ninguna asignada.
    is_deposit = models.BooleanField(
        default=False,
        verbose_name="Es el deposito de la sede"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Oficina"
        verbose_name_plural = "Oficinas"
        # El deposito cierra la lista de su sede: se elige a proposito, no
        # por ser el primero que aparece.
        ordering = ["branch", "is_deposit", "name"]

    def __str__(self):
        return f"{self.branch.name} - {self.name}"


class Zone(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="zones",
        verbose_name="Sede"
    )

    name = models.CharField(
        max_length=120,
        verbose_name="Zona"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Zona"
        verbose_name_plural = "Zonas"
        ordering = ["branch", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="unique_zone_per_branch"
            )
        ]

    def __str__(self):
        return f"{self.branch.name} - {self.name}"