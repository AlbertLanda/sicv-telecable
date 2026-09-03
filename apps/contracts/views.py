from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView, DetailView, FormView

from .forms import ContractCreateForm, InstallationWorkOrderForm
from .models import Contract
from apps.customers.models import Customer
from apps.services.models import Subscription
from apps.work_orders.location import resolve_location_display
from apps.work_orders.models import WorkOrder
from apps.work_orders.services import create_installation_work_order


class ContractCreateView(LoginRequiredMixin, CreateView):

    model = Contract
    form_class = ContractCreateForm
    template_name = "contracts/contract_create.html"

    def dispatch(self, request, *args, **kwargs):

        self.customer = get_object_or_404(
            Customer,
            pk=self.kwargs["customer_pk"],
            is_active=True,
        )

        return super().dispatch(
            request,
            *args,
            **kwargs,
        )

    def get_form_kwargs(self):

        kwargs = super().get_form_kwargs()

        kwargs["customer"] = self.customer

        return kwargs

    def get_initial(self):
        """
        Preselecciona la suscripción cuando se llega desde el resumen
        previo a la contratación (services:subscription_summary),
        que enlaza aquí con ?subscription=<id>. El campo sigue
        siendo editable: esto solo evita que el operador tenga que
        volver a buscar la suscripción que acaba de registrar.
        """

        initial = super().get_initial()

        subscription_id = self.request.GET.get("subscription")

        if subscription_id:
            initial["subscription"] = subscription_id

        return initial

    def get_preselected_subscription(self):
        subscription_id = self.request.GET.get("subscription")

        if not subscription_id:
            return None

        return (
            Subscription.objects
            .filter(
                pk=subscription_id,
                customer=self.customer,
                is_active=True,
                status=Subscription.Status.PRESALE,
            )
            .select_related("service_type", "plan", "address")
            .first()
        )

    def generate_contract_number(self):
        """
        Genera un número único de contrato.
        Formato: CONT-000001
        """

        last_contract = (
            Contract.objects
            .order_by("-id")
            .first()
        )

        if last_contract is None:
            next_number = 1
        else:
            next_number = last_contract.id + 1

        return f"CONT-{next_number:06d}"

    def form_valid(self, form):

        try:

            with transaction.atomic():

                contract = form.save(commit=False)

                contract.customer = self.customer

                contract.contract_number = (
                    self.generate_contract_number()
                )

                contract.status = Contract.Status.ACTIVE

                contract.save()

                self.object = contract

        except IntegrityError:

            form.add_error(
                None,
                (
                    "No fue posible registrar el contrato. "
                    "Verifique los datos e inténtelo nuevamente."
                ),
            )

            return self.form_invalid(form)

        messages.success(
            self.request,
            (
                "Contrato registrado correctamente. "
                f"Número: {self.object.contract_number}"
            ),
        )

        # -----------------------------------------------------------
        # RESUMEN DE CONTRATACIÓN
        #
        # Cierra el alta comercial FTTH del día con un resumen final
        # (cliente + domicilio + servicio/plan + contrato), en lugar
        # de volver directo a la ficha del cliente. Sin OT: la
        # generación de la Orden de Trabajo queda para la siguiente
        # jornada del sprint.
        # -----------------------------------------------------------

        return redirect(
            "contracts:contract_summary",
            customer_pk=self.customer.pk,
            pk=self.object.pk,
        )

    def get_context_data(self, **kwargs):

        context = super().get_context_data(**kwargs)

        context["customer"] = self.customer
        context["preselected_subscription"] = (
            self.get_preselected_subscription()
        )

        return context


class ContractSummaryView(LoginRequiredMixin, DetailView):
    """
    Resumen de contratación (día 02/09 del sprint FTTH).

    Cierra, de solo lectura, el alta comercial FTTH del día:
    cliente, domicilio, servicio/plan, suscripción y contrato ya
    registrados. Desde aquí también se puede generar la Orden de
    Trabajo de instalación (día 03/09), consumiendo
    create_installation_work_order() a través de
    InstallationWorkOrderCreateView: esta vista sigue siendo de solo
    lectura, no crea ninguna orden por sí misma.
    """

    model = Contract
    template_name = "contracts/contract_summary.html"
    context_object_name = "contract"

    def get_queryset(self):
        return (
            Contract.objects
            .filter(customer_id=self.kwargs["customer_pk"])
            .select_related(
                "customer",
                "subscription",
                "subscription__address",
                "subscription__address__zone",
                "subscription__service_type",
                "subscription__plan",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        subscription = self.object.subscription

        context["customer"] = self.object.customer
        context["subscription"] = subscription

        # -------------------------------------------------------------
        # ORDEN DE INSTALACIÓN (día 03/09)
        #
        # Se muestra la instalación más reciente de la suscripción, si
        # existe, en lugar de solo un booleano: así el resumen puede
        # comunicar tanto "ya se generó, número X, estado Y" como
        # "puede volver a intentarse" cuando la instalación anterior
        # quedó en un estado final que create_installation_work_order()
        # no bloquea (LIQUIDATED, REJECTED, NOT_FEASIBLE, CANCELLED).
        # -------------------------------------------------------------

        installation_order = (
            subscription.work_orders
            .filter(order_type__code="INSTALLATION")
            .select_related("order_type")
            .order_by("-created_at")
            .first()
        )

        context["installation_order"] = installation_order

        context["can_generate_installation_order"] = (
            installation_order is None
            or installation_order.status in WorkOrder.FINAL_STATUSES
        )

        context["can_request_installation_order"] = (
            self.request.user.has_perm("work_orders.add_workorder")
        )

        return context


class InstallationWorkOrderCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    FormView,
):
    """
    Formulario "Generar Orden de Instalación" del resumen de contratación.

    Revisión posterior al día 03/09 del sprint FTTH: antes era un único
    botón que creaba la orden en el mismo clic (POST directo, sin
    pantalla propia). Ahora "Generar Orden de Instalación" navega aquí
    (GET) para mostrar los datos que el contrato ya fija -cliente,
    dirección, plan- junto con lo que ATC sí puede decidir -observaciones,
    prioridad, motivo, tipo de atención y vendedor-, y solo crea la orden
    cuando se confirma el formulario (POST).

    El mismo permiso que ya protege la creación web de órdenes
    (work_orders.add_workorder, ver WorkOrderCreateView) protege esta
    acción: es la misma operación de dominio, solo con un punto de
    entrada distinto. No se define un permiso nuevo.

    create_installation_work_order() sigue siendo la única vía de
    creación que se consume aquí; esta vista no reimplementa ninguna
    regla del dominio de work_orders ni construye un WorkOrder
    directamente. `subscription` y `order_type` no son campos del
    formulario -la fachada los fija por sí misma-, así que ningún POST
    manipulado puede imponerlos. `attention_type` sí es un campo del
    formulario desde esta revisión: es ATC quien decide a propósito si la
    instalación es de Campo o de Sistema/NOC, y la fachada sigue aplicando
    FIELD por defecto si no llega ningún valor.
    """

    permission_required = "work_orders.add_workorder"
    form_class = InstallationWorkOrderForm
    template_name = "contracts/installation_order_form.html"

    def get_contract(self):
        """Contrato de la acción, resuelto una sola vez por petición."""
        if not hasattr(self, "_contract"):
            self._contract = get_object_or_404(
                Contract.objects
                .select_related(
                    "customer",
                    "customer__branch",
                    "subscription",
                    "subscription__address",
                    "subscription__address__zone",
                    "subscription__service_type",
                    "subscription__plan",
                ),
                pk=self.kwargs["pk"],
                customer_id=self.kwargs["customer_pk"],
            )

        return self._contract

    def _has_blocking_installation(self, subscription):
        """
        Mismo criterio que ContractSummaryView.can_generate_installation_order:
        una instalación que todavía no llegó a un estado final bloquea una
        nueva. Se repite aquí -y no solo en el resumen- para que abrir esta
        URL directamente, sin pasar por el botón, tampoco ofrezca un
        formulario condenado a fallar.
        """
        return (
            subscription.work_orders
            .filter(order_type__code="INSTALLATION")
            .exclude(status__in=WorkOrder.FINAL_STATUSES)
            .exists()
        )

    def get(self, request, *args, **kwargs):
        contract = self.get_contract()

        if self._has_blocking_installation(contract.subscription):
            messages.error(
                request,
                (
                    "La suscripción ya tiene una orden de instalación "
                    "abierta. Finalícela o anúlela antes de generar otra."
                ),
            )

            return redirect(
                "contracts:contract_summary",
                customer_pk=contract.customer_id,
                pk=contract.pk,
            )

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        contract = self.get_contract()

        context["contract"] = contract
        context["customer"] = contract.customer
        context["subscription"] = contract.subscription

        return context

    def form_valid(self, form):
        contract = self.get_contract()

        try:
            order = create_installation_work_order(
                subscription=contract.subscription,
                created_by=self.request.user,
                customer=contract.customer,
                reason=form.cleaned_data.get("reason"),
                priority=form.cleaned_data.get("priority") or None,
                detail=form.cleaned_data.get("detail", ""),
                attention_type=form.cleaned_data.get("attention_type") or None,
                seller=form.cleaned_data.get("seller"),
            )

        except ValidationError as exc:
            messages.error(
                self.request,
                " ".join(exc.messages),
            )

            # El servicio rechazó la generación (p. ej. ya hay una orden
            # de instalación abierta que apareció entre el GET y este
            # POST): se vuelve al resumen del contrato, que es donde se
            # explica el motivo y se ofrece el botón de nuevo si
            # corresponde. No hay ninguna orden que imprimir.
            return redirect(
                "contracts:contract_summary",
                customer_pk=contract.customer_id,
                pk=contract.pk,
            )

        messages.success(
            self.request,
            (
                f"Orden de instalación {order.order_number} "
                f"generada correctamente en estado "
                f"{order.get_status_display()}. Ya está "
                "disponible para el canal técnico."
            ),
        )

        # Orden generada: el siguiente paso es su comprobante, dentro del
        # propio namespace de contracts (ver InstallationOrderReceiptView).
        # No se redirige a una URL de work_orders: esta acción sigue
        # siendo responsabilidad del flujo comercial, no del módulo de
        # órdenes.
        return redirect(
            "contracts:installation_order_receipt",
            customer_pk=contract.customer_id,
            pk=contract.pk,
        )


class InstallationOrderReceiptView(LoginRequiredMixin, DetailView):
    """
    Comprobante de la Orden de Instalación generada desde el resumen de
    contratación.

    Se resuelve por contrato (mismo par customer_pk/pk que
    ContractSummaryView e InstallationWorkOrderCreateView), no por el pk
    de la orden: así toda la navegación de esta acción se queda dentro
    del namespace de contracts, sin depender de ninguna URL de
    work_orders.

    Decisiones deliberadas, según el alcance del sprint (ver punto 4 de
    la responsabilidad de Joleydi):

    - Es de solo lectura y reutiliza exactamente el mismo criterio que
      ContractSummaryView para ubicar la orden ("la más reciente de tipo
      INSTALLATION de la suscripción"): no se inventa una regla propia
      ni se reimplementa nada del dominio de work_orders.
    - Muestra los datos propios de la orden recién creada -cliente,
      código de cliente, teléfono, dirección, código de suministro,
      plan, estado, fecha de emisión, observaciones- junto con lo que
      ATC decidió al generarla (motivo, prioridad, tipo de atención,
      vendedor) y la ubicación GPS (ver resolve_location_display).
    - NO incluye NAP, borne, MAC/equipo, precinto, materiales ni
      evidencias: eso es la liquidación técnica, exclusiva del técnico
      asignado, y vive en la ficha de la orden (work_orders:detail,
      botón "Liquidar" de esta misma pantalla).
    - No agrega un permiso nuevo: el acceso es el mismo que ya exige
      ContractSummaryView (usuario autenticado), porque esta pantalla
      solo muestra en detalle datos que el resumen del contrato ya
      expone. El botón "Liquidar" hacia la ficha técnica sigue
      exigiendo work_orders.view_workorder, igual que en el resumen.
    """

    model = Contract
    template_name = "contracts/installation_order_receipt.html"
    context_object_name = "contract"

    def get_queryset(self):
        return (
            Contract.objects
            .filter(customer_id=self.kwargs["customer_pk"])
            .select_related(
                "customer",
                "customer__branch",
                "subscription",
                "subscription__address",
                "subscription__address__zone",
                "subscription__service_type",
                "subscription__plan",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        contract = self.object
        subscription = contract.subscription

        order = (
            subscription.work_orders
            .filter(order_type__code="INSTALLATION")
            .select_related(
                "order_type",
                "reason",
                "assigned_technician",
                "seller",
                "created_by",
            )
            .order_by("-created_at")
            .first()
        )

        if order is None:
            raise Http404(
                "Este contrato todavía no tiene una orden de "
                "instalación generada."
            )

        context["order"] = order
        context["customer"] = contract.customer
        context["subscription"] = subscription
        context["address"] = subscription.address

        # Misma función que ya usa la ficha técnica de la orden
        # (apps.work_orders.location): la dirección textual siempre se
        # muestra, y el botón de Maps solo ofrece coordenadas cuando son
        # válidas -nunca se inventan ni se corrigen aquí-.
        context["location"] = resolve_location_display(subscription.address)

        return context