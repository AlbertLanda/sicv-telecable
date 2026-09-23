from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

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
        constraints = [
            models.UniqueConstraint(
                fields=["subscription"],
                condition=models.Q(is_active=True),
                name="unique_active_contract_per_subscription",
            )
        ]

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

            if self.is_active and (
                Contract.objects
                .filter(subscription_id=self.subscription_id, is_active=True)
                .exclude(pk=self.pk)
                .exists()
            ):
                raise ValidationError({
                    "subscription": (
                        "La suscripción ya tiene un contrato activo. "
                        "Finalice o reemplace el vigente antes de registrar otro."
                    )
                })

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

def signed_contract_pdf_path(instance, filename):
    """Ruta del PDF firmado definitivo del contrato."""
    return (
        f"contracts/{instance.contract.contract_number}/"
        f"firmado/{filename}"
    )


def contract_signature_path(instance, filename):
    """Ruta de la firma, agrupada por contrato.

    Depende solo de la API de storage de Django -igual que las evidencias de
    la orden de trabajo-, para que cambiar el backend en produccion no
    obligue a tocar el modelo.
    """
    return f"contracts/{instance.contract.contract_number}/firma/{filename}"


class ContractSignature(models.Model):
    """La firma del abonado, capturada en campo sobre el contrato.

    El abonado firma una vez, en el domicilio, mientras el tecnico atiende la
    orden de instalacion. Por eso la firma cuelga del contrato -es el
    documento que se firma- y guarda ademas en que orden se recogio: es el
    unico rastro de donde estuvo el abonado con el movil delante.

    Se guarda el **trazo**, no el PDF firmado. El contrato se dibuja siempre
    desde sus datos (`document.py` decide que dice, `pdf.py` como se ve), asi
    que un PDF archivado seria una segunda version del mismo documento que
    podria dejar de coincidir con la primera. Con el trazo guardado, el
    contrato firmado es el mismo documento de siempre con un dato mas.

    Es uno por contrato: rehacer una firma reemplaza la anterior mientras la
    orden siga abierta, y al cerrarla queda la que el abonado acepto.
    """

    contract = models.OneToOneField(
        Contract,
        on_delete=models.CASCADE,
        related_name="signature",
        verbose_name="Contrato"
    )

    image = models.ImageField(
        upload_to=contract_signature_path,
        verbose_name="Firma del abonado",
        help_text="Trazo capturado en el movil del tecnico, con fondo transparente."
    )

    signer_name = models.CharField(
        max_length=200,
        verbose_name="Firmante",
        help_text=(
            "Nombre del abonado tal como estaba registrado al firmar. "
            "Se copia y no se enlaza: el papel dice quien firmo ese dia."
        )
    )

    work_order = models.ForeignKey(
        "work_orders.WorkOrder",
        on_delete=models.SET_NULL,
        related_name="contract_signatures",
        null=True,
        blank=True,
        verbose_name="Orden de instalación",
        help_text="Orden durante la cual se recogió la firma."
    )

    captured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="contract_signatures",
        null=True,
        blank=True,
        verbose_name="Capturada por"
    )

    signed_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="Fecha de firma"
    )

    signed_pdf = models.FileField(
        upload_to=signed_contract_pdf_path,
        blank=True,
        verbose_name="PDF firmado definitivo",
        help_text=(
            "Copia inmutable del documento aceptado por el abonado. "
            "Una vez firmado, las descargas oficiales leen este archivo."
        ),
    )

    signed_pdf_sha256 = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
        verbose_name="SHA-256 del PDF firmado",
    )

    signed_pdf_created_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name="PDF firmado archivado el",
    )

    document_anchor = models.JSONField(
        default=dict,
        blank=True,
        editable=False,
        verbose_name="Ancla de firma del documento",
    )

    # Dónde quedó el trazo dentro del hueco de firma, en puntos y medido
    # desde su esquina inferior izquierda. Vacío significa «como el sistema
    # la pone»: centrada sobre la línea. Se guarda relativo al hueco y no a
    # la página para que la firma siga a su línea si el documento cambia de
    # paginación, en vez de quedarse flotando donde estaba.
    offset_x = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Desplazamiento horizontal"
    )

    offset_y = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Desplazamiento vertical"
    )

    width = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Ancho del trazo",
        help_text="En puntos. Vacío deja el tamaño que el sistema calcula."
    )

    @property
    def colocacion(self):
        """El ajuste que hizo el técnico, o `None` si no tocó nada."""

        if self.offset_x is None and self.offset_y is None and self.width is None:
            return None

        return {
            "x": self.offset_x,
            "y": self.offset_y,
            "ancho": self.width,
        }

    class Meta:
        verbose_name = "Firma de contrato"
        verbose_name_plural = "Firmas de contrato"

    def __str__(self):
        return f"Firma de {self.contract.contract_number}"
