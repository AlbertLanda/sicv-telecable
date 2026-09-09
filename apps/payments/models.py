"""
Modelo de cobranza del SICV: qué debe el abonado, qué pagó y con qué recibo.

Cuatro entidades:

    Charge              lo que se le cobra al abonado (una mensualidad, la
                        instalación, un anexo). Nace del ciclo de facturación.
    Payment             el dinero que entra en caja, con su método.
    PaymentAllocation   qué parte de un pago cubre qué cargo.
    Receipt             la constancia numerada que se entrega al abonado.

El pago y el cargo no se tocan directamente: entre ambos va PaymentAllocation.
Un abonado que entrega S/ 120 sobre dos mensualidades de S/ 60 genera un pago
y dos aplicaciones, y así el historial responde tanto «cuánto entregó» como
«qué mes quedó cubierto». Amarrar el pago a un solo cargo obligaría a partir
el dinero recibido en registros que el abonado nunca hizo.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

from apps.customers.models import Customer
from apps.organization.models import Branch
from apps.services.models import Subscription


ZERO = Decimal("0.00")


class ChargeQuerySet(models.QuerySet):
    def outstanding(self):
        """Cargos que todavía suman deuda."""
        return self.filter(
            status__in=(Charge.Status.PENDING, Charge.Status.PARTIALLY_PAID)
        )

    def overdue(self, on=None):
        """Cargos vencidos: la fecha de vencimiento ya pasó y siguen abiertos."""
        return self.outstanding().filter(due_date__lt=on or timezone.localdate())


class Charge(models.Model):
    """
    Un concepto cobrable con fecha de vencimiento.

    El monto se guarda tal como se emitió. El descuento por pronto pago NO se
    resta de él: viaja aparte junto con su fecha límite, porque hasta que no
    se sabe *cuándo* paga el abonado no se sabe cuánto debe. Restarlo al
    emitir daría por concedido un descuento que todavía puede perderse, y el
    historial dejaría de poder explicar por qué se cobró una cifra distinta.
    """

    class Concept(models.TextChoices):
        MONTHLY = "MONTHLY", "Mensualidad"
        INSTALLATION = "INSTALLATION", "Instalación"
        ANNEX = "ANNEX", "Anexo"
        REACTIVATION = "REACTIVATION", "Reconexión"
        OTHER = "OTHER", "Otro concepto"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Pago parcial"
        PAID = "PAID", "Pagado"
        CANCELLED = "CANCELLED", "Anulado"

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="charges",
        verbose_name="Abonado",
    )

    # La suscripción es opcional: un cargo puede no venir de un servicio
    # contratado. El abonado, en cambio, siempre existe: sin él el cargo no se
    # le puede cobrar a nadie.
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name="charges",
        null=True,
        blank=True,
        verbose_name="Suscripción",
    )

    concept = models.CharField(
        max_length=20,
        choices=Concept.choices,
        verbose_name="Concepto",
    )

    description = models.CharField(
        max_length=160,
        verbose_name="Detalle",
    )

    # Fecha de emision. Se separa de created_at porque un cargo se puede
    # emitir con fecha del periodo que cubre -la mensualidad de septiembre
    # lleva fecha 01/09- aunque la fila se haya escrito otro dia.
    issued_on = models.DateField(
        default=timezone.localdate,
        verbose_name="Fecha",
    )

    # Cantidad del concepto. Casi siempre 1: una mensualidad, una reconexion.
    # Se guarda con cinco decimales porque el sistema anterior prorratea dias
    # de servicio y la fraccion tiene que caber sin redondear.
    # Cantidades y montos en negativo no existen en una deuda: lo que se le
    # devuelve al abonado es un pago o una anulación, no un cargo al revés. Se
    # frena en el campo y no solo en la pantalla, porque el cargo tambien se
    # emite desde el ciclo mensual y desde el servicio manual.
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=5,
        default=Decimal("1.00000"),
        validators=[MinValueValidator(Decimal("0.00001"))],
        verbose_name="Cantidad",
    )

    currency = models.CharField(
        max_length=3,
        default="PEN",
        verbose_name="Moneda",
    )

    # Cuando el cargo se recalcula solo al cambiar el plan o la tarifa. Los
    # cargos emitidos a mano suelen ser fijos y llevan esto en falso.
    auto_update = models.BooleanField(
        default=True,
        verbose_name="Actualizar automáticamente",
    )

    # Primer día del mes facturado. Es lo que convierte «una mensualidad» en
    # «la mensualidad de septiembre», y permite exigir que no se emita dos
    # veces el mismo mes para la misma suscripción.
    period = models.DateField(
        null=True,
        blank=True,
        verbose_name="Periodo facturado",
        help_text="Primer día del mes que cubre el cargo. Solo para mensualidades.",
    )

    # Ultimo dia cubierto. Con period forma el rango que la pantalla muestra
    # -«01/09/2026 - 30/09/2026»- y es lo que permite un cargo prorrateado
    # que no cubre el mes completo.
    period_end = models.DateField(
        null=True,
        blank=True,
        verbose_name="Cubre hasta",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Monto emitido",
    )

    due_date = models.DateField(
        verbose_name="Vence el",
    )

    # Cero es válido -no hay descuento-, negativo no: un descuento en
    # negativo subiría lo que el abonado debe sin que nada lo llame cargo.
    early_discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(ZERO)],
        verbose_name="Descuento por pronto pago",
    )

    discount_deadline = models.DateField(
        null=True,
        blank=True,
        verbose_name="Pronto pago hasta",
    )

    cut_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de corte prevista",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Estado",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ChargeQuerySet.as_manager()

    class Meta:
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"
        ordering = ["due_date", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="payments_charge_amount_positive",
            ),
            # El mes de una suscripción se cobra una sola vez. Es la garantía
            # de que volver a correr la generación de cargos no duplica deuda.
            models.UniqueConstraint(
                fields=["subscription", "period"],
                condition=Q(concept="MONTHLY"),
                name="payments_charge_unique_monthly_period",
            ),
        ]

    def __str__(self):
        return f"{self.get_concept_display()} · {self.description}"

    def clean(self):
        super().clean()

        if self.concept == self.Concept.MONTHLY and not self.period:
            raise ValidationError({
                "period": "Una mensualidad debe indicar el mes que cubre.",
            })

        if self.period and self.period.day != 1:
            raise ValidationError({
                "period": "El periodo se guarda con el primer día del mes.",
            })

        if self.early_discount and self.amount and self.early_discount >= self.amount:
            raise ValidationError({
                "early_discount": (
                    "El descuento por pronto pago no puede alcanzar al monto "
                    "del cargo."
                ),
            })

        if self.early_discount and not self.discount_deadline:
            raise ValidationError({
                "discount_deadline": (
                    "Un descuento por pronto pago necesita su fecha límite."
                ),
            })

    @property
    def paid_amount(self):
        """Lo aplicado a este cargo por pagos vigentes.

        Los pagos anulados no cuentan: anular devuelve la deuda a su sitio.
        """
        total = self.allocations.filter(
            payment__status=Payment.Status.REGISTERED
        ).aggregate(total=Sum("amount"))["total"]

        return total or ZERO

    def amount_due_on(self, day=None):
        """Cuánto cuesta cancelar el cargo ese día.

        Antes de la fecha límite vale el monto con descuento; después, el
        monto completo. Se pregunta por día porque la respuesta cambia sola
        con el calendario, sin que nadie edite el cargo.
        """
        day = day or timezone.localdate()

        if (
            self.early_discount
            and self.discount_deadline
            and day <= self.discount_deadline
        ):
            return self.amount - self.early_discount

        return self.amount

    def balance_on(self, day=None):
        """Lo que falta pagar ese día. Nunca negativo."""
        balance = self.amount_due_on(day) - self.paid_amount

        return balance if balance > ZERO else ZERO

    @property
    def balance(self):
        return self.balance_on()

    def is_overdue(self, on=None):
        on = on or timezone.localdate()

        return (
            self.status in (self.Status.PENDING, self.Status.PARTIALLY_PAID)
            and self.due_date < on
        )

    @property
    def current_discount(self):
        """El descuento que hoy se le concede a este cargo.

        Es la columna «Descuento» del comprobante: la diferencia entre el
        monto emitido y lo que cuesta cancelarlo hoy. Pasado el plazo de
        pronto pago vale cero, sin que nadie tenga que editar el cargo.
        """
        return self.amount - self.amount_due_on()

    @property
    def period_label(self):
        """El periodo como lo lee el operador: «01/09/2026 - 30/09/2026»."""
        if not self.period:
            return ""

        if not self.period_end:
            return f"{self.period:%d/%m/%Y}"

        return f"{self.period:%d/%m/%Y} - {self.period_end:%d/%m/%Y}"

    @property
    def paying_receipts(self):
        """Los comprobantes que cancelaron -total o parcialmente- este cargo.

        Es la columna «Documento» de la pantalla de deudas: vacia mientras el
        cargo no se haya cobrado.
        """
        return [
            allocation.payment.receipt
            for allocation in self.allocations.select_related(
                "payment", "payment__receipt"
            )
            if allocation.payment.status == Payment.Status.REGISTERED
            and hasattr(allocation.payment, "receipt")
        ]

    def active_commitment(self, on=None):
        """El compromiso vigente que protege este cargo, si existe.

        Un cargo comprometido sigue siendo deuda -aparece en el saldo- pero
        no debe empujar al abonado al corte mientras el plazo no venza.
        """
        on = on or timezone.localdate()

        return (
            self.commitments.filter(
                status=PaymentCommitment.Status.ACTIVE,
                committed_date__gte=on,
            )
            .order_by("committed_date")
            .first()
        )

    def is_protected_from_cut(self, on=None):
        return self.active_commitment(on) is not None

    def refresh_status(self, day=None, save=True):
        """Recalcula el estado a partir de lo aplicado.

        Vive en el cargo y no en la vista que registra el pago porque anular
        un pago tiene que poder devolver el cargo a PENDING con la misma
        regla, sin repetirla en otro sitio.
        """
        if self.status == self.Status.CANCELLED:
            return self.status

        paid = self.paid_amount

        if paid <= ZERO:
            self.status = self.Status.PENDING
        elif paid >= self.amount_due_on(day):
            self.status = self.Status.PAID
        else:
            self.status = self.Status.PARTIALLY_PAID

        if save:
            self.save(update_fields=["status", "updated_at"])

        return self.status


class Payment(models.Model):
    """
    Dinero recibido de un abonado, con el método por el que llegó.

    El método no es decorativo: un pago en efectivo lo respalda la caja, y uno
    por Yape o transferencia lo respalda el número de operación. Por eso todo
    método distinto de efectivo exige esa referencia.

    Un pago no se borra. Si estuvo mal, se anula: el registro permanece, la
    deuda vuelve sola -las aplicaciones dejan de contar- y el historial puede
    explicar qué pasó.
    """

    class Method(models.TextChoices):
        CASH = "CASH", "Efectivo"
        DEPOSIT = "DEPOSIT", "Depósito"
        TRANSFER = "TRANSFER", "Transferencia"
        CARD = "CARD", "Tarjeta de crédito"
        CHEQUE = "CHEQUE", "Cheque"
        YAPE = "YAPE", "Yape"
        PLIN = "PLIN", "Plin"

    class Status(models.TextChoices):
        # «Cancelado: No» del comprobante. El cobro quedo emitido pero el
        # dinero todavia no entro, asi que NO descuenta deuda: paid_amount
        # solo cuenta los pagos REGISTERED.
        PENDING = "PENDING", "Pendiente"
        REGISTERED = "REGISTERED", "Cancelado"
        VOIDED = "VOIDED", "Anulado"

    # Métodos que dejan rastro fuera del sistema y por eso se pueden conciliar.
    METHODS_REQUIRING_REFERENCE = (
        Method.YAPE,
        Method.PLIN,
        Method.TRANSFER,
        Method.DEPOSIT,
        Method.CARD,
        Method.CHEQUE,
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="Abonado",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Monto recibido",
    )

    method = models.CharField(
        max_length=20,
        choices=Method.choices,
        verbose_name="Método de pago",
    )

    reference = models.CharField(
        max_length=60,
        blank=True,
        verbose_name="Número de operación",
        help_text="Obligatorio para todo método que no sea efectivo.",
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="Sede que cobró",
    )

    received_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="Recibido el",
    )

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments_received",
        verbose_name="Usuario",
        help_text="Quien registro el cobro en el sistema.",
    )

    # El cobrador es quien trajo el dinero, y no siempre es quien lo registra:
    # un vendedor cobra en campo y la caja lo asienta. Separarlos es lo que
    # permite despues cuadrar por cobrador y no solo por usuario.
    collector = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments_collected",
        null=True,
        blank=True,
        verbose_name="Cobrador",
    )

    # Cuando entro el dinero. Con «Cancelado: Si» es el momento del cobro;
    # con «Pendiente» queda vacia hasta que se confirme.
    paid_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha y hora de pago",
    )

    # Hasta cuando vale el comprobante emitido como pendiente.
    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de vencimiento",
    )

    note = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Observación",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REGISTERED,
        verbose_name="Estado",
    )

    voided_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Anulado el",
    )
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments_voided",
        null=True,
        blank=True,
        verbose_name="Anulado por",
    )
    void_reason = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Motivo de la anulación",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ["-received_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="payments_payment_amount_positive",
            ),
        ]
        permissions = [
            # Cobrar y deshacer lo cobrado son capacidades distintas: quien
            # atiende la ventanilla no debería poder anular por su cuenta lo
            # que ya entró en caja.
            (
                "void_payment",
                "Puede anular pagos registrados",
            ),
        ]

    def __str__(self):
        return f"{self.get_method_display()} · S/ {self.amount}"

    def clean(self):
        super().clean()

        if (
            self.method in self.METHODS_REQUIRING_REFERENCE
            and not self.reference.strip()
        ):
            raise ValidationError({
                "reference": (
                    "Indique el número de operación: es lo que permite "
                    "conciliar el pago con el estado de cuenta."
                ),
            })

    @property
    def allocated_amount(self):
        total = self.allocations.aggregate(total=Sum("amount"))["total"]

        return total or ZERO

    @property
    def unallocated_amount(self):
        """Dinero recibido que todavía no cubre ningún cargo (saldo a favor)."""
        return self.amount - self.allocated_amount

    def confirm(self, paid_at=None):
        """Da por cobrado un pago emitido como pendiente.

        Recien aqui la deuda baja: mientras el pago esta PENDING sus
        aplicaciones no cuentan, porque el dinero no entro. Confirmarlo es lo
        que convierte el compromiso de la ventanilla en un cobro real.
        """
        if self.status != self.Status.PENDING:
            raise ValidationError(
                "Solo un pago pendiente se puede confirmar."
            )

        self.status = self.Status.REGISTERED
        self.paid_at = paid_at or timezone.now()
        self.save(update_fields=["status", "paid_at", "updated_at"])

        for allocation in self.allocations.select_related("charge"):
            allocation.charge.refresh_status()

        return self

    def void(self, user, reason):
        """Anula el pago y devuelve los cargos que cubría a su estado real."""
        reason = (reason or "").strip()

        if not reason:
            raise ValidationError("Debe indicar el motivo de la anulación.")

        if self.status == self.Status.VOIDED:
            raise ValidationError("El pago ya está anulado.")

        self.status = self.Status.VOIDED
        self.voided_at = timezone.now()
        self.voided_by = user
        self.void_reason = reason
        self.save(update_fields=[
            "status",
            "voided_at",
            "voided_by",
            "void_reason",
            "updated_at",
        ])

        for allocation in self.allocations.select_related("charge"):
            allocation.charge.refresh_status()

        return self


class PaymentAllocation(models.Model):
    """Qué parte de un pago cubre qué cargo."""

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="allocations",
        verbose_name="Pago",
    )

    charge = models.ForeignKey(
        Charge,
        on_delete=models.PROTECT,
        related_name="allocations",
        verbose_name="Cargo",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Monto aplicado",
    )

    # Descuento concedido en esta fila, normalmente el pronto pago. Se guarda
    # aparte del monto aplicado para que el comprobante pueda explicar por que
    # una mensualidad de S/ 79 se cerro con S/ 69: sin el, la resta quedaria
    # sin justificar en el papel que se le entrega al abonado.
    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Descuento",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Aplicación de pago"
        verbose_name_plural = "Aplicaciones de pago"
        ordering = ["charge__due_date", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="payments_allocation_amount_positive",
            ),
            # Un pago cubre un cargo una sola vez: si cubre más, se suma en la
            # misma fila. Dos filas para el mismo par harían que el recibo
            # mostrara el cargo repetido.
            models.UniqueConstraint(
                fields=["payment", "charge"],
                name="payments_allocation_unique_payment_charge",
            ),
        ]

    @property
    def gross_amount(self):
        """Monto antes del descuento: la columna «Monto» del comprobante."""
        return self.amount + self.discount

    def __str__(self):
        return f"{self.charge} <- S/ {self.amount}"


class ReceiptSequence(models.Model):
    """
    Correlativo persistente de los recibos, una fila por serie.

    Mismo criterio que el correlativo de órdenes: la fila se bloquea con
    select_for_update() antes de incrementarla, de modo que dos cajas que
    cobran a la vez no emiten el mismo número. Nunca se calcula leyendo el
    último recibo emitido.
    """

    series = models.CharField(
        max_length=8,
        unique=True,
        verbose_name="Serie",
    )

    last_number = models.PositiveIntegerField(
        default=0,
        verbose_name="Último correlativo emitido",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Correlativo de recibos"
        verbose_name_plural = "Correlativos de recibos"
        ordering = ["series"]

    def __str__(self):
        return f"{self.series}: {self.last_number}"


class Receipt(models.Model):
    """
    Constancia interna de un pago.

    No es un comprobante electrónico: no lleva serie SUNAT ni se declara. Es
    el papel que se le entrega al abonado para demostrar que pagó. Se modela
    aparte del pago -y no como dos campos dentro de él- para que emitir mañana
    una boleta o factura sobre el mismo pago no obligue a rehacer lo cobrado.
    """

    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name="receipt",
        verbose_name="Pago",
    )

    series = models.CharField(max_length=8, verbose_name="Serie")
    number = models.PositiveIntegerField(verbose_name="Correlativo")

    issued_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="Emitido el",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Comprobante de pago"
        verbose_name_plural = "Comprobantes de pago"
        ordering = ["-issued_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["series", "number"],
                name="payments_receipt_unique_series_number",
            ),
        ]

    def __str__(self):
        return self.full_number

    @property
    def full_number(self):
        return f"{self.series}-{self.number:06d}"

    @property
    def is_voided(self):
        """El recibo de un pago anulado deja de acreditar nada."""
        return self.payment.status == Payment.Status.VOIDED


class PaymentCommitment(models.Model):
    """
    Compromiso de pago: el abonado se obliga a pagar cargos concretos en una
    fecha, y hasta esa fecha no se le corta el servicio.

    Es un acuerdo, no un pago: no cancela deuda ni mueve el saldo. Lo único
    que cambia es que los cargos incluidos dejan de empujar hacia el corte
    mientras el compromiso siga vigente. Por eso se guarda con la fecha
    prometida, el motivo y quién lo concedió: si se rompe, hay que poder
    responder quién lo autorizó y sobre qué base.

    Se eligen cargos concretos y no "toda la deuda" porque el abonado se
    compromete por lo que puede: dejar el compromiso abierto a lo que aparezca
    después le daría protección sobre meses que todavía no existían cuando
    firmó.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Vigente"
        FULFILLED = "FULFILLED", "Cumplido"
        BROKEN = "BROKEN", "Incumplido"
        CANCELLED = "CANCELLED", "Anulado"

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="payment_commitments",
        verbose_name="Abonado",
    )

    charges = models.ManyToManyField(
        Charge,
        related_name="commitments",
        verbose_name="Cargos comprometidos",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Monto comprometido",
    )

    committed_date = models.DateField(
        verbose_name="Se compromete a pagar el",
    )

    reason = models.CharField(
        max_length=200,
        verbose_name="Motivo del compromiso",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="Estado",
    )

    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_commitments_granted",
        verbose_name="Registrado por",
        help_text="Quien registro el compromiso en el sistema.",
    )

    # Quien autoriza aplazar el corte. No siempre es quien lo teclea: la
    # ventanilla registra y un supervisor autoriza. Guardar solo al usuario
    # dejaria sin responsable la decision comercial.
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_commitments_authorized",
        null=True,
        blank=True,
        verbose_name="Autoriza",
    )

    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Cerrado el",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Compromiso de pago"
        verbose_name_plural = "Compromisos de pago"
        ordering = ["-committed_date", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="payments_commitment_amount_positive",
            ),
        ]
        permissions = [
            # Conceder un compromiso aplaza el corte de un abonado que ya
            # debe. Es una decision comercial, distinta de cobrar.
            (
                "grant_paymentcommitment",
                "Puede conceder compromisos de pago",
            ),
        ]

    def __str__(self):
        return f"Compromiso {self.committed_date:%d/%m/%Y} · S/ {self.amount}"

    def clean(self):
        super().clean()

        if not self.reason or not self.reason.strip():
            raise ValidationError({
                "reason": "Indique por qué se concede el compromiso.",
            })

    def is_expired(self, on=None):
        """La fecha prometida ya pasó y el compromiso sigue vigente."""
        on = on or timezone.localdate()

        return self.status == self.Status.ACTIVE and self.committed_date < on

    @property
    def outstanding_amount(self):
        """Lo que falta pagar de los cargos comprometidos."""
        return sum((charge.balance for charge in self.charges.all()), ZERO)

    def evaluate(self, day=None, save=True):
        """Cierra el compromiso cuando ya se sabe si se cumplió.

        Se cumple al quedar cancelados los cargos incluidos, y se incumple al
        pasar la fecha prometida con saldo pendiente. Mientras no ocurra
        ninguna de las dos cosas sigue vigente: un compromiso a futuro con
        deuda abierta es exactamente lo que se espera de él.
        """
        day = day or timezone.localdate()

        if self.status in (self.Status.CANCELLED, self.Status.FULFILLED):
            return self.status

        if self.outstanding_amount <= ZERO:
            self.status = self.Status.FULFILLED
            self.closed_at = timezone.now()
        elif self.committed_date < day:
            self.status = self.Status.BROKEN
            self.closed_at = timezone.now()
        else:
            self.status = self.Status.ACTIVE
            self.closed_at = None

        if save:
            self.save(update_fields=["status", "closed_at", "updated_at"])

        return self.status

    def cancel(self, user, reason=""):
        """Deja el compromiso sin efecto: el cargo vuelve a empujar al corte."""
        if self.status == self.Status.CANCELLED:
            raise ValidationError("El compromiso ya está anulado.")

        self.status = self.Status.CANCELLED
        self.closed_at = timezone.now()

        if reason.strip():
            self.reason = f"{self.reason} · Anulado: {reason.strip()}"

        self.save(update_fields=["status", "closed_at", "reason", "updated_at"])

        return self
