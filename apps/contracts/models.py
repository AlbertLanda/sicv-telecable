from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.customers.models import Customer
from apps.services.models import Plan, ServiceType, Subscription


class Contract(models.Model):
    """Contrato de servicio: lo que el abonado firma por cada servicio.

    Servicio y plan se guardan en el contrato y no solo en la suscripcion.
    El contrato es el documento, y un documento dice lo que se firmo: si el
    plan viviera unicamente en la suscripcion, cambiarlo manana reescribiria
    hacia atras lo que el abonado firmo hoy.

    Que sean dos registros con el mismo dato obliga a que no se contradigan,
    y de eso se encarga `clean()`: el plan tiene que pertenecer al servicio
    elegido, y la suscripcion que se contrata tiene que ser de ese mismo
    servicio y plan. La suscripcion sigue siendo el registro operativo -es la
    que instala, corta y factura-; el contrato, el respaldo comercial.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Borrador"
        ACTIVE = "ACTIVE", "Activo"
        SUSPENDED = "SUSPENDED", "Suspendido"
        CANCELLED = "CANCELLED", "Cancelado"
        FINISHED = "FINISHED", "Finalizado"

    class Modality(models.TextChoices):
        SALE = "SALE", "Venta"
        RENTAL = "RENTAL", "Alquiler"
        OWNED = "OWNED", "Propio"
        LOAN = "LOAN", "Préstamo"

    contract_number = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Número de contrato"
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Cliente"
    )

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Suscripción"
    )

    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Servicio"
    )

    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Plan"
    )

    modality = models.CharField(
        max_length=20,
        choices=Modality.choices,
        default=Modality.SALE,
        verbose_name="Modalidad",
        help_text=(
            "Cómo recibe el abonado el equipo del servicio contratado. "
            "La venta es lo habitual, así que el alta abre en ella."
        )
    )

    installments = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name="Cuotas",
        help_text="Cuotas pactadas en el contrato. Sin financiamiento es 1."
    )

    playhub_email = models.EmailField(
        blank=True,
        verbose_name="Correo PlayHub"
    )

    playhub_phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Celular PlayHub"
    )

    start_date = models.DateField(
        verbose_name="Fecha de inicio"
    )

    end_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de finalización"
    )

    last_activation_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Última activación",
        help_text=(
            "La estampa el sistema cuando el servicio queda activo. "
            "No se digita al registrar el contrato."
        )
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="Estado"
    )

    notes = models.TextField(
        blank=True,
        verbose_name="Observaciones"
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
        verbose_name = "Contrato"
        verbose_name_plural = "Contratos"
        ordering = ["-created_at"]

    def clean(self):
        super().clean()

        # El cliente lo pone la vista a partir de la URL, asi que durante la
        # validacion del formulario todavia no esta puesto. Cada regla
        # comprueba lo que tiene delante y calla sobre lo que aun no existe.

        if self.plan_id and self.service_type_id:
            if self.plan.service_type_id != self.service_type_id:
                raise ValidationError({
                    "plan": "El plan seleccionado no pertenece al servicio elegido."
                })

        if self.subscription_id:
            subscription = self.subscription

            if self.customer_id and subscription.customer_id != self.customer_id:
                raise ValidationError({
                    "subscription": "La suscripción seleccionada no pertenece al cliente."
                })

            if self.service_type_id and subscription.service_type_id != self.service_type_id:
                raise ValidationError({
                    "subscription": (
                        "La suscripción seleccionada es de otro servicio. "
                        "Elija una del servicio contratado."
                    )
                })

            if self.plan_id and subscription.plan_id != self.plan_id:
                raise ValidationError({
                    "subscription": (
                        "La suscripción seleccionada tiene otro plan. "
                        "El contrato y la suscripción deben coincidir."
                    )
                })

        # Las aplicaciones se entregan a una cuenta: sin correo ni celular el
        # abonado no puede usar lo que contrata. Al reves tambien importa -un
        # correo PlayHub guardado en un contrato de internet no lo lee
        # nadie-, asi que el dato solo se acepta donde significa algo.
        if self.service_type_id:
            requiere_playhub = self.service_type.requires_playhub_account

            correo = (self.playhub_email or "").strip()
            celular = (self.playhub_phone or "").strip()

            if requiere_playhub:
                faltantes = {}

                if not correo:
                    faltantes["playhub_email"] = (
                        "Indique el correo PlayHub del abonado."
                    )

                if not celular:
                    faltantes["playhub_phone"] = (
                        "Indique el celular PlayHub del abonado."
                    )

                if faltantes:
                    raise ValidationError(faltantes)

            elif correo or celular:
                raise ValidationError({
                    "playhub_email": (
                        "Los datos PlayHub solo corresponden a servicios "
                        "que se entregan a una cuenta."
                    )
                })

    def __str__(self):
        return f"{self.contract_number} - {self.customer}"