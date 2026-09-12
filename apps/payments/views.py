"""
Pantallas de cobranza del abonado: deuda, historial de pagos y comprobantes.

Las tres cuelgan de un abonado concreto porque así se consultan en ventanilla:
primero se ubica al cliente y después se mira su cuenta. Son pestañas de la
ficha del cliente -el mismo abonado visto desde otro ángulo-, no entradas de
un menú global: una entrada global tendría que adivinar de qué abonado se
habla y acabaría dependiendo de un estado que el operador no ve.
"""

from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.core.paginator import Paginator

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView, View

from apps.customers.models import Customer
from apps.organization.context_processors import (
    get_active_branch,
    get_active_office,
)

from .forms import (
    ChargeCreateForm,
    PaymentCommitmentForm,
    PaymentRegisterForm,
    PaymentVoidForm,
)
from .models import (
    Charge,
    ChargeConcept,
    Payment,
    PaymentCommitment,
    Receipt,
    ZERO,
    format_receipt_number,
)
from .pdf import render_receipt
from .services import (
    BILLING_MONTH_DAYS,
    DEFAULT_RECEIPT_SERIES,
    authorizer_options,
    collector_options,
    create_manual_charge,
    customer_commitments,
    customer_debt,
    daily_rate,
    grant_commitment,
    monthly_reference,
    outstanding_charges,
    receipt_series_options,
    register_payment,
)


#: Marca que el tablero de deuda pone en su formulario. Distingue «vengo de
#: marcar filas» de «vengo del menú de la ficha», que es un caso legítimo sin
#: nada marcado: el abonado que adelanta dinero sin deber todavía nada.
BOARD_ORIGIN = "tablero"


class BoardSelectionRequiredMixin:
    """Devuelve al tablero si se pidió actuar sobre filas y no había ninguna.

    «Cobrar» y «Compromiso» actúan sobre lo marcado. Sin marcas, la pantalla
    de destino se abría en blanco y el operador tenía que deducir que el
    problema estaba en el tablero que acababa de dejar atrás.

    Solo se aplica al que viene del tablero. Entrar a cobrar sin selección
    sigue siendo válido desde el menú de la ficha, que es como se registra un
    adelanto.
    """

    selection_message = "Marque las deudas sobre las que quiere actuar."

    def board_selection(self):
        raise NotImplementedError

    def get(self, request, *args, **kwargs):
        came_from_board = request.GET.get("origen") == BOARD_ORIGIN

        if came_from_board and not self.board_selection():
            messages.warning(request, self.selection_message)

            return redirect("payments:debt", pk=self.customer.pk)

        return super().get(request, *args, **kwargs)


class CustomerScopedMixin:
    """Resuelve el abonado de la URL y lo deja disponible para la plantilla.

    Se declara *después* de PermissionRequiredMixin en cada vista, a
    proposito: asi el control de acceso corre antes de buscar al abonado y un
    usuario sin permiso no puede averiguar por la diferencia entre 403 y 404
    que ese codigo de cliente existe.
    """

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.customer = None

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(Customer, pk=kwargs["pk"])

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["customer"] = self.customer
        context["debt"] = customer_debt(self.customer)

        return context


class CustomerDebtView(PermissionRequiredMixin, CustomerScopedMixin, TemplateView):
    """Lo que el abonado debe hoy, cargo por cargo."""

    template_name = "payments/customer_debt.html"
    permission_required = "payments.view_charge"

    # 15 filas, como el resto de tablas del abonado. El selector conserva los
    # tamanos grandes porque "Cobrar" y "Compromiso" actuan sobre las filas
    # marcadas y la marca no cruza de pagina: para saldar una mora larga de
    # una vez, el operador necesita poder verla entera.
    PAGE_SIZES = (15, 30, 50, 100, 500)
    DEFAULT_PAGE_SIZE = 15

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        page_size = self._resolve_page_size()
        context["page_sizes"] = self.PAGE_SIZES
        context["page_size"] = page_size

        # Solo la tabla se pagina. Los totales siguen saliendo de `debt`, que
        # cuenta la deuda entera: si leyeran de la pagina, dirian "15 deudas
        # abiertas" cuando el abonado tiene 30.
        paginator = Paginator(context["debt"]["charges"], page_size)
        page_obj = paginator.get_page(self.request.GET.get("page"))
        context["paginator"] = paginator
        context["page_obj"] = page_obj
        context["is_paginated"] = page_obj.has_other_pages()

        # Cada boton del tablero responde a su propio permiso: emitir deuda,
        # cobrarla y aplazar su corte son tres decisiones distintas.
        context["can_create_charge"] = user.has_perm("payments.add_charge")
        context["can_register_payment"] = user.has_perm("payments.add_payment")
        context["can_grant_commitment"] = user.has_perm(
            "payments.grant_paymentcommitment"
        )

        context["active_commitments"] = [
            commitment
            for commitment in customer_commitments(self.customer)
            if commitment.status == PaymentCommitment.Status.ACTIVE
        ]

        return context

    def _resolve_page_size(self):
        raw = self.request.GET.get("filas")

        if raw and raw.isdigit() and int(raw) in self.PAGE_SIZES:
            return int(raw)

        return self.DEFAULT_PAGE_SIZE


class CustomerPaymentHistoryView(
    PermissionRequiredMixin, CustomerScopedMixin, ListView
):
    """Todo lo que el abonado pagó, incluidos los pagos anulados.

    Los anulados no se ocultan: quien consulta el historial necesita ver que
    hubo un cobro y que se deshizo, no encontrarse un hueco sin explicación.

    Una fila por deuda pagada y no por pago, que es como lo lee el sistema que
    se reemplaza y como lo pregunta el abonado: «¿octubre está pagado?», no
    «¿qué cubrió el cobro del martes?». Un pago que cubrió tres mensualidades
    sale en tres filas, cada una con su periodo y su vencimiento, y las tres
    apuntan al mismo comprobante. Agrupado por pago, el periodo y el
    vencimiento no cabían en la fila -son tres distintos- y la tabla no podía
    llevar las columnas de la deuda.
    """

    template_name = "payments/customer_payment_history.html"
    context_object_name = "rows"
    paginate_by = 15
    permission_required = "payments.view_payment"

    def get_queryset(self):
        payments = (
            Payment.objects.filter(customer=self.customer)
            .select_related("received_by", "branch", "receipt", "collector")
            .prefetch_related("allocations__charge")
        )

        rows = []

        for payment in payments:
            allocations = list(payment.allocations.all())

            # Un cobro sin aplicar -un adelanto, un saldo a favor- no tiene
            # deuda que lo explique, pero tiene que salir igual: si solo se
            # listaran las aplicaciones, el dinero que el abonado entregó a
            # cuenta desapareceria del historial.
            if not allocations:
                rows.append(self._row(payment, None))
                continue

            for allocation in allocations:
                rows.append(self._row(payment, allocation))

        return rows

    def _row(self, payment, allocation):
        """Una fila de la tabla, con las columnas de la deuda que cubrió."""
        charge = allocation.charge if allocation else None

        return {
            "payment": payment,
            "charge": charge,
            # La fecha del pago, no la de emisión del cargo: lo que esta
            # pantalla cuenta es cuándo entró el dinero.
            "date": payment.paid_at or payment.received_at,
            "quantity": charge.quantity if charge else None,
            "detail": charge.description if charge else "Pago a cuenta",
            "period": charge.period_label if charge else "",
            "currency": charge.currency if charge else "PEN",
            # El monto emitido, antes del descuento, para que «Monto» quiera
            # decir lo mismo aquí que en el tablero de deuda y en el cobro.
            "amount": (
                allocation.gross_amount if allocation else payment.amount
            ),
            "receipt": getattr(payment, "receipt", None),
            "due_date": charge.due_date if charge else payment.due_date,
            "note": payment.note,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_void_payment"] = self.request.user.has_perm(
            "payments.void_payment"
        )

        return context


class CustomerReceiptsView(PermissionRequiredMixin, CustomerScopedMixin, ListView):
    """Los comprobantes emitidos al abonado."""

    template_name = "payments/customer_receipts.html"
    context_object_name = "receipts"
    paginate_by = 15
    permission_required = "payments.view_receipt"

    def get_queryset(self):
        return (
            Receipt.objects.filter(payment__customer=self.customer)
            .select_related("payment", "payment__received_by", "payment__branch")
        )


class PaymentRegisterView(
    PermissionRequiredMixin,
    CustomerScopedMixin,
    BoardSelectionRequiredMixin,
    TemplateView,
):
    """
    Cobro en ventanilla.

    El operador puede repartir el monto entre cargos concretos o dejar que se
    aplique del más antiguo al más nuevo. Lo que no se aplique queda como
    saldo a favor en el pago: no se inventa un cargo para absorberlo.
    """

    template_name = "payments/payment_register.html"
    permission_required = "payments.add_payment"
    selection_message = "Marque la deuda que va a cobrar."

    def board_selection(self):
        return self._selected_charges(list(outstanding_charges(self.customer)))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        charges = list(outstanding_charges(self.customer))
        selected = self._selected_charges(charges)

        # El cobro se arma con lo que el operador marco en el tablero. El
        # monto llega ya sumado -y con el pronto pago aplicado cuando
        # corresponde- para que no tenga que recalcular a mano lo que las
        # filas ya decian.
        series = receipt_series_options()

        # La pantalla se abre con el comprobante que se emitiria si el
        # operador no cambiara nada, asi que el talonario propuesto es el
        # primero que sabe decir que numero le toca. Encabezan la lista los
        # blocks de un cobrador, que vienen numerados de papel: abrir en uno
        # de esos dejaria el numero en blanco y un «Aceptar» sin tocar nada
        # devolveria un error por algo que el operador no eligio.
        propuesto = next(
            (sequence for sequence in series if sequence.autonumber),
            series[0] if series else None,
        )
        inicial = {
            "settled": "1",
            "series": propuesto.code if propuesto else None,
            # Formateado, como el del papel: el campo es una cadena y lo que
            # el operador tiene delante al abrir la pantalla tiene que leerse
            # igual que el comprobante que se va a entregar.
            "number": (
                format_receipt_number(propuesto.next_number)
                if propuesto
                else ""
            ),
        }

        if selected and "form" not in kwargs:
            context["form"] = PaymentRegisterForm(
                initial=dict(
                    inicial,
                    amount=sum((charge.balance for charge in selected), ZERO),
                )
            )

        context.setdefault("form", PaymentRegisterForm(initial=inicial))
        context["charges"] = charges
        context["selected_charges"] = selected
        context["selected_ids"] = [charge.pk for charge in selected]
        context["selected_total"] = sum(
            (charge.balance for charge in selected), ZERO
        )
        context["selected_gross"] = sum(
            (charge.amount for charge in selected), ZERO
        )
        context["selected_discount"] = sum(
            (charge.amount - charge.balance_on() for charge in selected), ZERO
        )
        context["today"] = timezone.localdate()
        context["now"] = timezone.localtime()
        context["receipt_series"] = series

        return context

    def _selected_charges(self, charges):
        """Los cargos que venian marcados en el tablero de deudas.

        Se filtran contra los cargos abiertos del abonado y no se confia en
        los ids del enlace: asi un id ajeno o ya pagado no entra al cobro.
        """
        raw = self.request.GET.getlist("charges") or self.request.POST.getlist(
            "charges"
        )
        wanted = {value for value in raw if value.isdigit()}

        if not wanted:
            return []

        return [charge for charge in charges if str(charge.pk) in wanted]

    def post(self, request, *args, **kwargs):
        form = PaymentRegisterForm(request.POST)
        charges = list(outstanding_charges(self.customer))

        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        try:
            allocations = self._read_allocations(request.POST, charges)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.render_to_response(self.get_context_data(form=form))

        # Sin reparto explicito se cobra lo marcado en el tablero, cada cargo
        # por su saldo. Es lo que el operador acaba de elegir; caer al reparto
        # por antiguedad cobraria otra cosa distinta de la que marco.
        if allocations is None:
            selected = self._selected_charges(charges)
            allocations = [
                (charge, charge.balance) for charge in selected
            ] or None

        branch = get_active_branch(request)

        # Donde se esta cobrando lo dice la barra superior y solo ella. La
        # ficha lo muestra pero no lo pregunta: eran dos sitios para decidir
        # lo mismo, y el que se quedaba sin mirar -el de la barra- seguia
        # gobernando el resto de la sesion.
        #
        # Sin oficinas cargadas queda en blanco y el cobro sigue: la sede
        # basta para saber que caja lo recibio.
        office = get_active_office(request, branch=branch)

        if branch is None:
            form.add_error(
                None,
                "Seleccione una sede activa antes de registrar el cobro: el "
                "pago se registra a nombre de la caja que lo recibe.",
            )
            return self.render_to_response(self.get_context_data(form=form))

        try:
            payment, receipt = register_payment(
                customer=self.customer,
                amount=form.cleaned_data["amount"],
                method=form.cleaned_data["method"],
                branch=branch,
                office=office,
                user=request.user,
                reference=form.cleaned_data["reference"],
                note=form.cleaned_data["note"],
                allocations=allocations,
                series=form.cleaned_data.get("series") or DEFAULT_RECEIPT_SERIES,
                number=form.cleaned_data.get("number"),
                collector=form.cleaned_data.get("collector"),
                settled=form.cleaned_data.get("settled", True),
                due_date=form.cleaned_data.get("due_date"),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.render_to_response(self.get_context_data(form=form))

        if payment.status == Payment.Status.PENDING:
            messages.success(
                request,
                f"Comprobante {receipt.full_number} emitido como pendiente "
                f"por S/ {payment.amount}. La deuda no baja hasta confirmarlo.",
            )
        else:
            messages.success(
                request,
                f"Cobro registrado por S/ {payment.amount}. "
                f"Comprobante {receipt.full_number}.",
            )

        return redirect("payments:receipt_detail", pk=receipt.pk)

    def _read_allocations(self, data, charges):
        """Lee el reparto que envió la pantalla, un campo por cargo.

        Devuelve None cuando no se indicó ninguno, para que el servicio
        aplique el criterio por defecto en vez de registrar un pago sin
        aplicar a nada.
        """
        allocations = []

        for charge in charges:
            raw = (data.get(f"charge_{charge.pk}") or "").strip()

            if not raw:
                continue

            try:
                value = Decimal(raw)
            except (InvalidOperation, ValueError):
                raise ValidationError(
                    f"El monto aplicado al cargo «{charge.description}» no es "
                    f"un número válido."
                )

            if value <= ZERO:
                continue

            allocations.append((charge, value))

        return allocations or None


class ReceiptScopedMixin:
    """El comprobante con todo lo que hace falta para describirlo entero.

    Lo comparten la pantalla y el PDF: son el mismo documento por dos
    salidas, y dejar que cada uno arme su consulta era la forma segura de que
    uno acabara mostrando un dato que el otro no.
    """

    def get_queryset(self):
        return Receipt.objects.select_related(
            "payment",
            "payment__customer",
            "payment__branch",
            "payment__office",
            "payment__received_by",
            "payment__collector",
            "sequence",
        ).prefetch_related("payment__allocations__charge")


class ReceiptDetailView(
    LoginRequiredMixin, PermissionRequiredMixin, ReceiptScopedMixin, DetailView
):
    """El comprobante emitido, con la misma ficha con la que se cobró.

    Todo bloqueado: un comprobante emitido no se corrige, se anula y se emite
    otro. Lo que se imprime o se descarga no es esta pantalla sino el PDF, que
    es el papel de verdad; esta solo se consulta.
    """

    model = Receipt
    template_name = "payments/receipt_detail.html"
    context_object_name = "receipt"
    permission_required = "payments.view_receipt"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.object.payment
        allocations = list(payment.allocations.all())

        context["customer"] = payment.customer
        context["allocations"] = allocations
        context["printed_number"] = format_receipt_number(self.object.number)

        # La hora del cobro sale de `paid_at` cuando existe, porque un
        # comprobante emitido como pendiente se cobra despues: la fecha en que
        # entro el dinero no es la de emision.
        context["paid_at"] = payment.paid_at or payment.received_at

        # Los medios se listan enteros, con el usado marcado, en vez de
        # escribir solo su nombre: la ficha de cobro los muestra asi y esta es
        # la misma ficha. El operador reconoce de un vistazo que ese cobro fue
        # en efectivo porque la marca esta donde siempre.
        context["methods"] = Payment.Method.choices

        context["totals"] = {
            "gross": sum((a.gross_amount for a in allocations), ZERO),
            "discount": sum((a.discount for a in allocations), ZERO),
            "net": sum((a.amount for a in allocations), ZERO),
        }

        return context


class ReceiptPdfView(
    LoginRequiredMixin, PermissionRequiredMixin, ReceiptScopedMixin, DetailView
):
    """El comprobante como PDF, para verlo o para llevarselo.

    Un solo documento con dos entregas, que es lo que separan los dos botones
    de la ficha:

    - «Imprimir» lo abre con `?ver=1` y llega *inline*: el navegador lo pinta
      en su propio visor, en la pestana de al lado, con la barra de imprimir y
      descargar que el operador ya conoce. Antes esto reabria la pantalla HTML
      y lanzaba el dialogo encima, que duplicaba la ficha y tapaba la
      consulta.
    - «Descargar PDF» lo pide sin `ver` y llega como `attachment`: se guarda
      en el disco, que es lo que dice el boton.

    La misma vista para los dos porque es el mismo papel; lo unico que cambia
    es donde acaba.
    """

    model = Receipt
    permission_required = "payments.view_receipt"

    def render_to_response(self, context, **kwargs):
        buffer = BytesIO()
        nombre = render_receipt(self.object, buffer)
        buffer.seek(0)

        return FileResponse(
            buffer,
            as_attachment=self.request.GET.get("ver") != "1",
            filename=nombre,
        )


class PaymentVoidView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Anula un pago y devuelve los cargos que cubría a su estado real."""

    permission_required = "payments.void_payment"

    def post(self, request, pk):
        payment = get_object_or_404(
            Payment.objects.select_related("customer"), pk=pk
        )
        form = PaymentVoidForm(request.POST)

        if not form.is_valid():
            messages.error(request, "Debe indicar el motivo de la anulación.")
            return redirect("payments:history", pk=payment.customer_id)

        try:
            payment.void(user=request.user, reason=form.cleaned_data["reason"])
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect("payments:history", pk=payment.customer_id)

        messages.success(
            request,
            f"Pago de S/ {payment.amount} anulado. La deuda vuelve a reflejarlo.",
        )

        return redirect("payments:history", pk=payment.customer_id)


class ChargeCreateView(PermissionRequiredMixin, CustomerScopedMixin, TemplateView):
    """
    Botón «Nuevo» del tablero de deuda: emite un cargo a mano.

    La mensualidad no se ofrece aquí. La emite el ciclo automático desde el
    plan contratado, y crearla a mano competiría con ese ciclo hasta
    duplicarle el mes al abonado.
    """

    template_name = "payments/charge_create.html"
    permission_required = "payments.add_charge"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("form", ChargeCreateForm(customer=self.customer))
        context["today"] = timezone.localdate()

        # Mensualidad con la que "Calcular dias segun monto" prorratea, y lo
        # que sale de dividirla. Se calculan aqui y no en el navegador para
        # que la cifra que el operador ve sea la misma que la del servidor:
        # dos redondeos distintos sobre el mismo plan darian dos deudas.
        reference = monthly_reference(self.customer)

        context["monthly_reference"] = reference
        context["daily_rate"] = daily_rate(reference)
        context["billing_month_days"] = BILLING_MONTH_DAYS
        context["monthly_concept"] = Charge.Concept.MONTHLY

        # Si el boton de prorrateo nace visible o escondido. Lo decide el
        # servidor y no el navegador para que la pantalla llegue ya pintada:
        # en el caso normal -mensualidad- el boton no debe aparecer un
        # instante despues, ni asomar y esconderse en un formulario que
        # vuelve con errores sobre otro concepto.
        #
        # Con el catalogo en la base, quien manda es la familia del concepto
        # elegido: mensualidad es una de doscientas y pico opciones, y son
        # todas las recurrentes -un plan, un alquiler, un enlace- las que se
        # reparten en dias.
        form = context["form"]
        selected = form["concept"].value()
        concept = None

        if selected:
            concept = ChargeConcept.objects.filter(pk=selected).first()

        context["es_mensualidad"] = bool(concept and concept.is_monthly)

        return context

    def post(self, request, *args, **kwargs):
        form = ChargeCreateForm(request.POST, customer=self.customer)

        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        try:
            concept = form.cleaned_data["concept"]

            charge = create_manual_charge(
                customer=self.customer,
                # La familia gobierna el comportamiento de la deuda; el
                # concepto del catalogo dice que se le cobro al abonado.
                concept=concept.family,
                concept_item=concept,
                description=form.cleaned_data["description"],
                amount=form.cleaned_data["amount"],
                due_date=form.cleaned_data["due_date"],
                subscription=form.cleaned_data.get("subscription"),
                quantity=form.cleaned_data.get("quantity"),
                auto_update=form.cleaned_data.get("auto_update", False),
                early_discount=form.cleaned_data.get("early_discount"),
                discount_deadline=form.cleaned_data.get("discount_deadline"),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.render_to_response(self.get_context_data(form=form))

        messages.success(
            request,
            f"Cargo emitido: {charge.description} por S/ {charge.amount}.",
        )

        return redirect("payments:debt", pk=self.customer.pk)


class PaymentCommitmentCreateView(
    PermissionRequiredMixin,
    CustomerScopedMixin,
    BoardSelectionRequiredMixin,
    TemplateView,
):
    """
    Botón «Compromiso» del tablero de deuda.

    El operador elige los cargos que el abonado se compromete a pagar y la
    fecha. No mueve saldo: la deuda sigue siendo la misma, y lo único que
    cambia es que esos cargos dejan de empujar al corte hasta ese día.
    """

    template_name = "payments/commitment_create.html"
    permission_required = "payments.grant_paymentcommitment"
    selection_message = "Marque las deudas que entran en el compromiso."

    def board_selection(self):
        return self._read_selected_charges(self.request.GET)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        charges = list(outstanding_charges(self.customer))
        selected = self._read_selected_charges(
            self.request.GET if self.request.method == "GET" else self.request.POST
        )

        context.setdefault("form", PaymentCommitmentForm())
        context["charges"] = charges
        context["selected_charges"] = selected
        context["selected_ids"] = [charge.pk for charge in selected]
        context["selected_total"] = sum(
            (charge.balance for charge in selected), ZERO
        )
        context["commitments"] = customer_commitments(self.customer)
        context["now"] = timezone.localtime()

        return context

    def post(self, request, *args, **kwargs):
        form = PaymentCommitmentForm(request.POST)
        selected = self._read_selected_charges(request.POST)

        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        try:
            commitment = grant_commitment(
                customer=self.customer,
                charges=selected,
                committed_date=form.cleaned_data["committed_date"],
                reason=form.cleaned_data["reason"],
                amount=form.cleaned_data.get("amount"),
                user=request.user,
                authorized_by=form.cleaned_data.get("authorized_by"),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.render_to_response(self.get_context_data(form=form))

        messages.success(
            request,
            f"Compromiso registrado por S/ {commitment.amount} "
            f"para el {commitment.committed_date:%d/%m/%Y}.",
        )

        return redirect("payments:debt", pk=self.customer.pk)

    def _read_selected_charges(self, data):
        """Los cargos marcados en el tablero de deudas.

        Se filtran contra los cargos abiertos del abonado: un id ajeno o ya
        pagado que llegue en el enlace no entra al compromiso.
        """
        selected_ids = [
            value for value in data.getlist("charges") if value.isdigit()
        ]

        if not selected_ids:
            return []

        return list(
            outstanding_charges(self.customer).filter(pk__in=selected_ids)
        )


class PaymentCommitmentCancelView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Deja un compromiso sin efecto: sus cargos vuelven a empujar al corte."""

    permission_required = "payments.grant_paymentcommitment"

    def post(self, request, pk):
        commitment = get_object_or_404(
            PaymentCommitment.objects.select_related("customer"), pk=pk
        )

        try:
            commitment.cancel(
                user=request.user,
                reason=(request.POST.get("reason") or "").strip(),
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect("payments:debt", pk=commitment.customer_id)

        messages.success(request, "Compromiso anulado.")

        return redirect("payments:debt", pk=commitment.customer_id)
