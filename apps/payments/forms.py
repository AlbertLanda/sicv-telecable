"""Formularios de caja."""

from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator
from django.utils import timezone

from .models import Charge, ChargeConcept, Payment, ZERO
from .services import default_concept, monthly_reference


class ConceptSelect(forms.Select):
    """Desplegable de conceptos que lleva la familia de cada uno.

    El prorrateo en días solo pertenece a la mensualidad, y con el catálogo
    en la base ya no basta con mirar el valor de la opción: cuál de los
    doscientos y pico conceptos se comporta como mensualidad lo dice su
    familia. Viaja en cada `<option>` para que la pantalla lo resuelva sin
    preguntarle al servidor en cada cambio del desplegable.
    """

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(
            name, value, label, selected, index, **kwargs
        )

        # La opción vacía no tiene concepto detrás; el resto llega como
        # `ModelChoiceIteratorValue`, que sí trae la instancia.
        concept = getattr(value, "instance", None)

        if concept is not None:
            option["attrs"]["data-family"] = concept.family

        return option


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
            "quantity",
            "description",
            "amount",
            "due_date",
            "auto_update",
        ]
        widgets = {
            # `format` explicito: un <input type="date"> solo entiende
            # aaaa-mm-dd, y con el idioma en español Django pinta 09/09/2026,
            # que el navegador descarta dejando el campo en blanco.
            "due_date": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            ),
            "description": forms.Textarea(attrs={"rows": 6}),
            # `min` frena tambien la flecha del spinner, que es por donde se
            # llega al negativo sin darse cuenta: se baja de 1 a 0 y de 0 a
            # -1 sin escribir nada.
            "amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            # Cantidad bloqueada en 1. La deuda se emite de a una: lo que
            # varia entre un caso y otro es el monto, no cuantas veces se
            # cobra el mismo concepto. Se muestra porque es la pantalla que el
            # operador tiene aprendida, no para que la escriba.
            "quantity": forms.NumberInput(
                attrs={"class": "tc-input tc-readonly tc-w-sm"}
            ),
        }
        labels = {
            "due_date": "Paga hasta",
            "description": "Descripción",
        }

    # Declarado aparte y no como el campo del modelo: en el cargo, `concept`
    # es la familia -las cuatro que el sistema sabe tratar- y en la pantalla
    # es el concepto exacto del catálogo. La vista traduce lo segundo en lo
    # primero al emitir.
    concept = forms.ModelChoiceField(
        label="Concepto",
        queryset=ChargeConcept.objects.none(),
        empty_label=None,
        widget=ConceptSelect,
    )

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

        self.fields["description"].required = False

        # `disabled` y no solo el atributo del widget: un campo deshabilitado
        # no viaja en el POST, y sin esto Django lo leeria como vacio. Asi toma
        # siempre el valor inicial, aunque alguien reescriba el formulario
        # desde el navegador.
        self.fields["quantity"].required = False
        self.fields["quantity"].disabled = True

        # Un 1 pelado y no 1.00000: los cinco decimales existen para repartir
        # consumos, no para leerse en un campo que siempre dice lo mismo. En
        # la base sigue guardandose con la escala de la columna.
        self.fields["quantity"].initial = Decimal("1")

        # El catálogo se resuelve al construir el formulario y no en el
        # módulo: una lista fijada al importar no vería un concepto dado de
        # alta desde el admin hasta reiniciar el servidor.
        #
        # Sin opción vacía -«---------» no era una respuesta posible, el
        # concepto es obligatorio- y abriendo en mensualidad, que es lo que se
        # emite a diario.
        self.fields["concept"].queryset = ChargeConcept.objects.filter(
            is_active=True
        )
        self.fields["concept"].initial = default_concept()

        # Paga hasta arranca hoy, como en el sistema anterior. Es una fecha
        # que el operador mueve, no una que tenga que escribir desde cero.
        self.fields["due_date"].initial = timezone.localdate()

        # Marcado por defecto ahora que la pantalla abre en mensualidad: esa
        # si sigue al plan, y si la tarifa cambia antes de que la paguen, el
        # cargo tiene que acompañarla. Para un cargo fijo -una reconexion- el
        # operador lo desmarca.
        self.fields["auto_update"].initial = True

        # El monto llega escrito con la mensualidad del abonado, que es el
        # caso normal, y queda editable: un prorrateo o un acuerdo de
        # ventanilla se escriben encima.
        if customer is not None:
            reference = monthly_reference(customer)

            if reference > ZERO:
                self.fields["amount"].initial = reference

        _style_widgets(self)

    def clean_quantity(self):
        return self.cleaned_data.get("quantity") or Decimal("1.00000")

    def clean(self):
        """El pronto pago no se emite a mano.

        Lo concede el ciclo mensual desde la politica de cobro del plan, que
        es donde vive la regla. La pantalla no lo pide, y dejarlo en cero aqui
        cierra la puerta a que llegue por el POST de todos modos.
        """
        cleaned = super().clean()

        cleaned["early_discount"] = ZERO
        cleaned["discount_deadline"] = None

        # Sin descripción se usa el nombre del concepto. La pantalla de deudas
        # muestra el detalle en su propia columna: dejarla vacía daría una fila
        # que no dice qué se le está cobrando.
        #
        # Va aquí y no en un `clean_description` porque el concepto se declara
        # despues de los campos del modelo, y cuando le toca el turno a la
        # descripcion todavia no esta limpio.
        if not (cleaned.get("description") or "").strip():
            concept = cleaned.get("concept")
            cleaned["description"] = concept.name if concept else "Cargo"

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
