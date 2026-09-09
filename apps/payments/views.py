"""
Pantallas de cobranza del abonado: deuda, historial de pagos y comprobantes.

Las tres cuelgan de un abonado concreto porque así se consultan en ventanilla:
primero se ubica al cliente y después se mira su cuenta. Son pestañas de la
ficha del cliente -el mismo abonado visto desde otro ángulo-, no entradas de
un menú global: una entrada global tendría que adivinar de qué abonado se
habla y acabaría dependiendo de un estado que el operador no ve.
"""

from decimal import Decimal, InvalidOperation

from django.core.paginator import Paginator

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView, View

from apps.customers.models import Customer
from apps.organization.context_processors import get_active_branch
from apps.services.models import Subscription

from .forms import (
    ChargeCreateForm,
    PaymentCommitmentForm,
    PaymentRegisterForm,
    PaymentVoidForm,
)
from .models import Charge, Payment, PaymentCommitment, Receipt, ZERO
from .services import (
    DEFAULT_RECEIPT_SERIES,
    authorizer_options,
    collector_options,
    create_manual_charge,
    customer_commitments,
    customer_debt,
    grant_commitment,
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
    """

    template_name = "payments/customer_payment_history.html"
    context_object_name = "payments"
    paginate_by = 15
    permission_required = "payments.view_payment"

    def get_queryset(self):
        return (
            Payment.objects.filter(customer=self.customer)
            .select_related("received_by", "branch", "receipt")
            .prefetch_related("allocations__charge")
        )

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
        if selected and "form" not in kwargs:
            context["form"] = PaymentRegisterForm(
                initial={
                    "amount": sum(
                        (charge.balance for charge in selected), ZERO
                    ),
                    "settled": "1",
                }
            )

        context.setdefault("form", PaymentRegisterForm(initial={"settled": "1"}))
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
        series = receipt_series_options()
        context["receipt_series"] = series

        # Solo informativo: el numero definitivo lo asigna el correlativo al
        # aceptar, bajo bloqueo. Mostrar el proximo aqui no lo reserva.
        context["next_number"] = (series[0].last_number + 1) if series else 1

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
                user=request.user,
                reference=form.cleaned_data["reference"],
                note=form.cleaned_data["note"],
                allocations=allocations,
                series=form.cleaned_data.get("series") or DEFAULT_RECEIPT_SERIES,
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


class ReceiptDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """El comprobante tal como se entrega al abonado.

    Con `?print=1` la plantilla lanza la impresión del navegador, igual que la
    orden inicial de trabajo.
    """

    model = Receipt
    template_name = "payments/receipt_detail.html"
    context_object_name = "receipt"
    permission_required = "payments.view_receipt"

    def get_queryset(self):
        return Receipt.objects.select_related(
            "payment",
            "payment__customer",
            "payment__branch",
            "payment__received_by",
        ).prefetch_related("payment__allocations__charge")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["customer"] = self.object.payment.customer
        context["autoprint"] = self.request.GET.get("print") == "1"

        return context


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

        # Mensualidad con la que "Calcular dias segun monto" prorratea. Sale
        # de la suscripcion activa del abonado; sin ninguna, el boton lo dice
        # en vez de calcular sobre un cero.
        active = self.customer.subscriptions.filter(
            status=Subscription.Status.ACTIVE
        ).first()
        context["monthly_reference"] = (
            active.total_monthly_price if active else ZERO
        )

        return context

    def post(self, request, *args, **kwargs):
        form = ChargeCreateForm(request.POST, customer=self.customer)

        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        try:
            charge = create_manual_charge(
                customer=self.customer,
                concept=form.cleaned_data["concept"],
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
