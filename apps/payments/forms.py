"""Formularios de caja."""

from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator

from apps.services.models import Subscription

from .models import Charge, Payment, ZERO


def subscription_label(subscription):
    """Cómo se lee una suscripción en un desplegable del propio abonado.

    `Subscription.__str__` antepone el nombre del cliente, que aquí sobra: la
    pantalla ya es la de ese abonado y no hay ninguna otra a la que pudiera
    referirse. Lo que hacía era ocupar el ancho del campo y empujar el plan
    -lo único que distingue una suscripción de otra- fuera de la vista.

    Se identifica por número de servicio, tipo y plan, que es como el operador
    las nombra. El estado solo aparece cuando no es el esperado: una activa no
    necesita anunciarlo, una suspendida sí, porque cambia la conversación.
    """
    label = "#%s · %s · %s" % (
        subscription.service_number,
        subscription.service_type.name,
        subscription.plan.name,
    )

    if subscription.status != Subscription.Status.ACTIVE:
        label += " (%s)" % subscription.get_status_display()

    return label


def _style_widgets(form):
    """Aplica al formulario el trazo del sistema visual compartido.

    Se recorre en bloque en lugar de declarar la clase en cada widget: así un
    campo que se agregue despues no se queda con el aspecto por defecto de
    Bootstrap, que en estas pantallas se ve de otra aplicacion.
    """
    for field in form.fields.values():
        widget = field.widget

        if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
            widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(widget, forms.Select):
            widget.attrs.setdefault("class", "form-select")
        else:
            widget.attrs.setdefault("class", "form-control")


class PaymentRegisterForm(forms.Form):
    """
    Datos de un cobro en ventanilla.

    El reparto entre cargos no se pide aquí: llega como un campo por cargo en
    el POST y lo resuelve la vista, porque cuántos cargos hay depende del
    abonado y no del formulario.
    """

    amount = forms.DecimalField(
        label="Total",
        min_value=Decimal("0.01"),
        max_digits=10,
        decimal_places=2,
    )

    series = forms.ChoiceField(
        label="Serie",
        required=False,
    )

    method = forms.ChoiceField(
        label="Medio de pago",
        choices=Payment.Method.choices,
        widget=forms.RadioSelect,
    )

    # «Cancelado: Si / No (Pendiente)» del comprobante. Un pendiente queda
    # emitido pero no baja la deuda hasta confirmarlo.
    # No obligatorio y con «Sí» por defecto: el caso normal es que el dinero
    # ya entro, y exigirlo haria fallar todo cobro que no lo envie explicito.
    settled = forms.ChoiceField(
        label="Cancelado",
        choices=(("1", "Sí"), ("0", "No (Pendiente)")),
        initial="1",
        required=False,
        widget=forms.RadioSelect,
    )

    reference = forms.CharField(
        label="Número de operación",
        max_length=60,
        required=False,
    )

    collector = forms.ModelChoiceField(
        label="Cobrador",
        queryset=None,
        required=False,
        empty_label="Seleccione un vendedor",
    )

    due_date = forms.DateField(
        label="Fecha de vencimiento",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    note = forms.CharField(
        label="Observaciones",
        max_length=200,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Las series y los cobradores se resuelven al construir el formulario
        # y no en el modulo: una lista fijada al importar no veria una serie
        # nueva ni un vendedor recien creado hasta reiniciar el servidor.
        from .services import collector_options, receipt_series_options

        self.fields["series"].choices = [
            (sequence.series, sequence.series)
            for sequence in receipt_series_options()
        ]
        self.fields["collector"].queryset = collector_options()

        _style_widgets(self)

    def clean_reference(self):
        return (self.cleaned_data.get("reference") or "").strip()

    def clean_settled(self):
        """Solo un «No» explícito deja el comprobante pendiente."""
        return self.cleaned_data.get("settled") != "0"

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("method")
        reference = cleaned.get("reference", "")

        # Se repite la regla del modelo a propósito: aquí el operador puede
        # corregirla en pantalla, mientras que en el modelo es la última
        # defensa para cualquier otra vía de escritura.
        if method in Payment.METHODS_REQUIRING_REFERENCE and not reference:
            self.add_error(
                "reference",
                "Indique el número de operación: es lo que permite conciliar "
                "el pago con el estado de cuenta.",
            )

        return cleaned


class PaymentVoidForm(forms.Form):
    """Anular un pago exige decir por qué: el registro se conserva."""

    reason = forms.CharField(
        label="Motivo de la anulación",
        max_length=200,
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get("reason") or "").strip()

        if not reason:
            raise forms.ValidationError("Debe indicar el motivo de la anulación.")

        return reason


class ChargeCreateForm(forms.ModelForm):
    """
    Emisión manual de un cargo, para lo que el ciclo mensual no genera.

    La mensualidad la emite sola el ciclo desde el plan y su política de cobro.
    Emitirla a mano tambien se permite -el sistema anterior lo permite y hay
    casos que lo necesitan-, y lo que evita cobrar dos veces el mes de una
    suscripción es la restricción única de (suscripción, periodo), no que la
    pantalla esconda el concepto.
    """

    class Meta:
        model = Charge
        fields = [
            "subscription",
            "concept",
            "quantity",
            "description",
            "amount",
            "due_date",
            "auto_update",
            "early_discount",
            "discount_deadline",
        ]
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "discount_deadline": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": "En blanco se usa el nombre del concepto.",
                }
            ),
            # `min` frena tambien la flecha del spinner, que es por donde se
            # llega al negativo sin darse cuenta: se baja de 1 a 0 y de 0 a
            # -1 sin escribir nada.
            "amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "quantity": forms.NumberInput(
                attrs={"min": "0.00001", "step": "0.00001"}
            ),
            "early_discount": forms.NumberInput(
                attrs={"min": "0", "step": "0.01"}
            ),
        }
        labels = {
            "due_date": "Paga hasta",
            "description": "Descripción",
        }

    def __init__(self, *args, customer=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.customer = customer

        # Una deuda en negativo no existe: lo que se le devuelve al abonado es
        # un pago o una anulacion, no un cargo al reves. El modelo ya lo
        # rechaza; declararlo aqui ademas da el error en el campo y no al
        # final, y evita que un monto invalido llegue a `cleaned_data`.
        self.fields["amount"].validators.append(
            MinValueValidator(Decimal("0.01"))
        )
        self.fields["quantity"].validators.append(
            MinValueValidator(Decimal("0.00001"))
        )
        self.fields["early_discount"].validators.append(
            MinValueValidator(ZERO)
        )

        self.fields["subscription"].required = False
        self.fields["early_discount"].required = False
        self.fields["discount_deadline"].required = False
        self.fields["description"].required = False

        # Cantidad no obligatoria: casi siempre es 1 -una mensualidad, una
        # reconexion- y en blanco se asume esa, en vez de rechazar la deuda
        # por un campo que el operador no tenia que pensar.
        self.fields["quantity"].required = False
        self.fields["quantity"].initial = Decimal("1.00000")

        # Emitida a mano, la deuda es fija: no la recalcula un cambio de plan.
        # Es lo contrario que en la mensualidad del ciclo, que si se actualiza.
        self.fields["auto_update"].initial = False

        _style_widgets(self)

        # Solo las suscripciones del abonado: ofrecer las de todos permitiría
        # colgarle un cargo del servicio de otra persona.
        if customer is not None:
            self.fields["subscription"].queryset = (
                customer.subscriptions.select_related("service_type", "plan")
            )

        # select_related arriba: sin el, pintar el desplegable consulta el tipo
        # y el plan una vez por opcion.
        self.fields["subscription"].label_from_instance = subscription_label
        self.fields["subscription"].empty_label = "Sin servicio asociado"

    def clean_description(self):
        """Sin descripción se usa el nombre del concepto.

        La pantalla de deudas muestra el detalle en su propia columna: dejarla
        vacía daría una fila que no dice qué se le está cobrando.
        """
        description = (self.cleaned_data.get("description") or "").strip()

        if description:
            return description

        concept = self.data.get("concept")

        return dict(Charge.Concept.choices).get(concept, "Cargo")

    def clean_quantity(self):
        return self.cleaned_data.get("quantity") or Decimal("1.00000")

    def clean(self):
        cleaned = super().clean()

        if not cleaned.get("early_discount"):
            cleaned["early_discount"] = ZERO

        return cleaned


class PaymentCommitmentForm(forms.Form):
    """
    Compromiso de pago sobre cargos concretos.

    Los cargos llegan como un campo por fila del tablero de deuda, igual que
    en el cobro: cuántos hay depende del abonado y no del formulario.
    """

    committed_date = forms.DateField(
        label="Se compromete a pagar el",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    amount = forms.DecimalField(
        label="Monto comprometido",
        min_value=Decimal("0.01"),
        max_digits=10,
        decimal_places=2,
        required=False,
        help_text="En blanco se compromete el saldo completo de lo elegido.",
    )

    authorized_by = forms.ModelChoiceField(
        label="Autoriza",
        queryset=None,
        required=False,
        empty_label="",
    )

    reason = forms.CharField(
        label="Motivo del compromiso",
        max_length=200,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from .services import authorizer_options

        self.fields["authorized_by"].queryset = authorizer_options()

        _style_widgets(self)

    def clean_reason(self):
        reason = (self.cleaned_data.get("reason") or "").strip()

        if not reason:
            raise forms.ValidationError(
                "Indique por qué se concede el compromiso: aplazar un corte "
                "es una decisión que alguien tiene que poder explicar."
            )

        return reason
