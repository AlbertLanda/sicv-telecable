from django.db import models

from apps.organization.models import Branch, Zone


class Customer(models.Model):

    class DocumentType(models.TextChoices):
        DNI = "DNI", "DNI"
        RUC = "RUC", "RUC"
        CE = "CE", "Carné de Extranjería"
        PASSPORT = "PASSPORT", "Pasaporte"

    class PersonType(models.TextChoices):
        NATURAL = "NATURAL", "Persona Natural"
        LEGAL = "LEGAL", "Persona Jurídica"

    # ---------------------------------------------------------------
    # REGLA DE CORRESPONDENCIA DOCUMENTO / TIPO DE PERSONA
    #
    # Fuente única de verdad para evitar combinaciones incoherentes
    # como RUC + Persona Natural o DNI + Persona Jurídica. Se usa
    # tanto en los formularios (apps/customers/forms.py) como en las
    # vistas (apps/customers/views.py), por lo que el tipo de persona
    # nunca depende únicamente de lo que el usuario elija en pantalla.
    # ---------------------------------------------------------------

    DOCUMENT_PERSON_TYPE_MAP = {
        DocumentType.DNI: PersonType.NATURAL,
        DocumentType.CE: PersonType.NATURAL,
        DocumentType.PASSPORT: PersonType.NATURAL,
        DocumentType.RUC: PersonType.LEGAL,
    }

    @classmethod
    def person_type_for_document(cls, document_type):
        """
        Devuelve el tipo de persona esperado para un tipo de documento,
        según la tabla de correspondencia obligatoria del flujo de
        registro (DNI/CE/PASAPORTE -> NATURAL, RUC -> LEGAL).

        Devuelve None si el tipo de documento no es reconocido.
        """

        return cls.DOCUMENT_PERSON_TYPE_MAP.get(document_type)

    code = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Código de abonado"
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="customers",
        verbose_name="Sede"
    )

    document_type = models.CharField(
        max_length=15,
        choices=DocumentType.choices,
        verbose_name="Tipo de documento"
    )

    document_number = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="Número de documento"
    )

    person_type = models.CharField(
        max_length=15,
        choices=PersonType.choices,
        default=PersonType.NATURAL,
        verbose_name="Tipo de persona"
    )

    first_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Nombres"
    )

    paternal_surname = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Primer apellido"
    )

    maternal_surname = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Segundo apellido"
    )

    business_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Razón social / Nombre comercial"
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Teléfono principal"
    )

    secondary_phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Teléfono secundario"
    )

    email = models.EmailField(
        blank=True,
        verbose_name="Correo electrónico"
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
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ["paternal_surname", "maternal_surname", "first_name"]

        constraints = [
            models.UniqueConstraint(
                fields=["document_type", "document_number"],
                name="unique_customer_document"
            )
        ]

    def __str__(self):
        if self.person_type == self.PersonType.LEGAL:
            return self.business_name or self.document_number

        full_name = " ".join(
            filter(
                None,
                [
                    self.first_name,
                    self.paternal_surname,
                    self.maternal_surname,
                ],
            )
        )

        return full_name or self.document_number


class CustomerAddress(models.Model):

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="addresses",
        verbose_name="Cliente"
    )

    zone = models.ForeignKey(
        Zone,
        on_delete=models.PROTECT,
        related_name="customer_addresses",
        null=True,
        blank=True,
        verbose_name="Zona"
    )

    address = models.CharField(
        max_length=250,
        verbose_name="Dirección"
    )

    reference = models.CharField(
        max_length=300,
        blank=True,
        verbose_name="Referencia"
    )

    district = models.CharField(
        max_length=120,
        verbose_name="Distrito"
    )

    meter_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Número de medidor"
    )

    electrical_supply_code = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        verbose_name="Código de suministro eléctrico"
    )

    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        verbose_name="Latitud"
    )

    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        verbose_name="Longitud"
    )

    gps_link = models.URLField(
        max_length=500,
        blank=True,
        verbose_name="Enlace GPS"
    )

    is_primary = models.BooleanField(
        default=True,
        verbose_name="Dirección principal"
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
        verbose_name = "Dirección del cliente"
        verbose_name_plural = "Direcciones del cliente"

    def __str__(self):
        return f"{self.customer} - {self.address}"
