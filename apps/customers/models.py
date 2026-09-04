from django.db import models

from apps.customers.coordinates import (
    build_gps_link,
    normalize_coordinate_pair,
)
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

    DOCUMENT_PERSON_TYPE_MAP = {
        DocumentType.DNI: PersonType.NATURAL,
        DocumentType.CE: PersonType.NATURAL,
        DocumentType.PASSPORT: PersonType.NATURAL,
        DocumentType.RUC: PersonType.LEGAL,
    }

    @classmethod
    def person_type_for_document(cls, document_type):
        return cls.DOCUMENT_PERSON_TYPE_MAP.get(document_type)

    # -------------------------------------------------------------
    # CÓDIGO DE ABONADO POR SEDE (mejora solicitada 02/09)
    #
    # Formato: {PREFIJO}01-A{correlativo de 7 dígitos}, por ejemplo
    # HY01-A0000001 para el primer cliente de Huancayo. "01" y "A"
    # son fijos (una sola oficina y una sola serie, por ahora); el
    # correlativo es independiente por sede.
    #
    # El prefijo se busca por Branch.code, que es como están
    # sembradas las 3 sedes reales del sprint (ver
    # apps/organization/migrations/0002_seed_sedes_reales.py). Una
    # sede sin prefijo aquí (por ejemplo, una sede creada a mano para
    # pruebas) no rompe el alta: se deriva un prefijo de sus propias
    # letras en vez de cortar el registro del cliente.
    # -------------------------------------------------------------

    BRANCH_CODE_PREFIXES = {
        "HUANCAYO": "HY",
        "JAUJA": "JA",
        "OROYA": "OR",
    }

    @classmethod
    def _prefix_for_branch(cls, branch):
        prefix = cls.BRANCH_CODE_PREFIXES.get(branch.code)

        if prefix:
            return prefix

        derived = "".join(
            ch for ch in branch.code.upper() if ch.isalpha()
        )[:2]

        return derived or "SD"

    @classmethod
    def generate_code(cls, branch):
        """
        Genera el siguiente código de abonado para `branch`.

        El correlativo se calcula a partir del código más alto ya
        usado en esa sede (no de un conteo de filas), para no repetir
        números si algún cliente de esa sede quedó inactivo. Como
        todos los correlativos de una misma sede comparten el mismo
        prefijo y ancho fijo (7 dígitos con ceros a la izquierda), el
        orden alfabético de los códigos coincide con el orden
        numérico: no hace falta parsear todos los códigos, solo el
        último.
        """

        code_prefix = f"{cls._prefix_for_branch(branch)}01-A"

        last_code = (
            cls.objects
            .filter(
                branch=branch,
                code__startswith=code_prefix,
            )
            .order_by("-code")
            .values_list("code", flat=True)
            .first()
        )

        last_number = 0

        if last_code:
            suffix = last_code[len(code_prefix):]

            if suffix.isdigit():
                last_number = int(suffix)

        return f"{code_prefix}{last_number + 1:07d}"

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

    # --- Ubicación publicable --------------------------------------------
    #
    # Los campos `latitude`, `longitude` y `gps_link` guardan lo que llegó:
    # pueden contener `0.0000000` —el centinela de «sin georreferencia» de
    # Distriluz— y un enlace construido sobre ese cero. Estas propiedades son
    # lo que debe **mostrarse**, y aplican la regla única de
    # `apps.customers.coordinates`: cero, vacío, medio par o fuera del planeta
    # no son una ubicación, así que se publican como `None`.
    #
    # Se exponen como propiedades porque las plantillas no pueden llamar
    # funciones con argumentos, y las tres fichas que muestran ubicación
    # —cliente, resumen del contrato y Orden Técnica— deben coincidir. No hay
    # migración: los campos almacenados no cambian.

    @property
    def map_latitude(self):
        """Latitud publicable, o `None` si el par no es una ubicación real."""
        return normalize_coordinate_pair(self.latitude, self.longitude)[0]

    @property
    def map_longitude(self):
        """Longitud publicable, o `None` si el par no es una ubicación real."""
        return normalize_coordinate_pair(self.latitude, self.longitude)[1]

    @property
    def map_link(self):
        """Enlace de mapa, o cadena vacía si no hay coordenadas válidas.

        Se **deriva** de las coordenadas en lugar de devolver `gps_link`: el
        enlace almacenado pudo construirse sobre un `0,0` antes de esta regla,
        y servirlo tal cual sería la puerta de atrás por la que el dato falso
        vuelve a aparecer en pantalla.
        """
        return build_gps_link(self.latitude, self.longitude)

    @property
    def electrical_supply_number(self):
        """Alias temporal de compatibilidad con la rama previa al rename."""
        return self.electrical_supply_code

    @electrical_supply_number.setter
    def electrical_supply_number(self, value):
        self.electrical_supply_code = value

    def __str__(self):
        return f"{self.customer} - {self.address}"
