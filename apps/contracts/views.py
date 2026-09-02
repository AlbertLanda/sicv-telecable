from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import CreateView, DetailView

from .forms import ContractCreateForm
from .models import Contract
from apps.customers.models import Customer
from apps.services.models import Subscription
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
    View,
):
    """
    Acción "Generar Orden de Instalación" del resumen de contratación
    (día 03/09 del sprint FTTH).

    Es una vista de un solo POST, sin formulario: todos los datos que
    necesita create_installation_work_order() (suscripción, cliente,
    sede, zona) ya están fijados por el contrato que se está cerrando,
    así que no hay nada que el operador deba volver a escribir.

    El mismo permiso que ya protege la creación web de órdenes
    (work_orders.add_workorder, ver WorkOrderCreateView) protege esta
    acción: es la misma operación de dominio, solo con un punto de
    entrada distinto. No se define un permiso nuevo.

    create_installation_work_order() es la única vía de creación que
    se consume aquí; esta vista no reimplementa ninguna regla del
    dominio de work_orders ni construye un WorkOrder directamente.
    """

    permission_required = "work_orders.add_workorder"
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        contract = get_object_or_404(
            Contract.objects
            .select_related(
                "customer",
                "subscription",
                "subscription__customer__branch",
                "subscription__address__zone",
            ),
            pk=self.kwargs["pk"],
            customer_id=self.kwargs["customer_pk"],
        )

        try:
            order = create_installation_work_order(
                subscription=contract.subscription,
                created_by=request.user,
                customer=contract.customer,
            )

        except ValidationError as exc:
            messages.error(
                request,
                " ".join(exc.messages),
            )

            # El servicio rechazó la generación (p. ej. ya hay una orden
            # de instalación abierta): se vuelve al resumen del contrato,
            # que es donde se explica el motivo y se ofrece el botón de
            # nuevo si corresponde. No hay ninguna orden que imprimir.
            return redirect(
                "contracts:contract_summary",
                customer_pk=contract.customer_id,
                pk=contract.pk,
            )

        messages.success(
            request,
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
    - El comprobante NO incluye NAP, borne, materiales, fotografías ni
      firmas: esa parte (liquidación técnica completa) queda fuera de
      este sprint (punto 4.2) y se incorporará más adelante, junto con
      el resto del flujo de liquidación de campo.
    - No agrega un permiso nuevo: el acceso es el mismo que ya exige
      ContractSummaryView (usuario autenticado), porque este comprobante
      solo muestra en detalle datos que el resumen del contrato ya
      expone.
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
            .select_related("order_type", "assigned_technician", "created_by")
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

        return context