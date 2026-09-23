from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import CreateView, DetailView, FormView

from .forms import ContractCreateForm, InstallationWorkOrderForm
from .signatures import firma_del_contrato
from .subscriptions import (
    codigo_de_suscripcion,
    resolver_suscripcion,
    suscripciones_contratables,
)
from .models import Contract
from apps.customers.models import Customer
from apps.services.catalog import plans_by_service_type, service_type_config
from apps.services.models import ServiceType, Subscription
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

    # El alta arranca en DUO. Es el servicio que más se contrata, así que
    # abrir la pantalla ya en él ahorra el paso que el operador daba
    # siempre; y el plan queda en el primero de ese servicio, el mismo que
    # encabeza el combo, para que la pantalla nazca entera en vez de a
    # medio llenar. Ambos se cambian como cualquier otro campo.
    SERVICIO_POR_DEFECTO = "DUO"

    def get_form_kwargs(self):

        kwargs = super().get_form_kwargs()

        kwargs["customer"] = self.customer

        return kwargs

    def catalogo_de_planes(self):
        """Los planes por servicio, una sola vez por petición.

        Lo leen el valor inicial del formulario y el javascript de la
        pantalla, y los dos tienen que ver el mismo orden: el plan por
        defecto es «el primero del combo», y eso solo se sostiene si la
        lista es la misma.
        """

        if not hasattr(self, "_catalogo_de_planes"):
            self._catalogo_de_planes = plans_by_service_type()

        return self._catalogo_de_planes

    def servicio_y_plan_por_defecto(self):
        servicio = (
            ServiceType.objects
            .filter(code=self.SERVICIO_POR_DEFECTO, is_active=True)
            .first()
        )

        if servicio is None:
            return None, None

        planes = self.catalogo_de_planes().get(servicio.pk) or []

        return servicio.pk, (planes[0]["id"] if planes else None)

    def get_initial(self):
        """
        Cuando se llega desde el resumen previo a la contratación
        (services:subscription_summary, que enlaza aquí con
        ?subscription=<id>), la pantalla abre con el servicio y el plan de
        esa suscripción: son los que el contrato tiene que declarar para
        que la suscripción que se resuelva sea justamente esa.

        Llegando desde la ficha, sin suscripción a cuestas, abre en el
        servicio por defecto.
        """

        initial = super().get_initial()

        initial["start_date"] = timezone.localdate()

        subscription = self.get_preselected_subscription()

        if subscription is not None:
            initial["service_type"] = subscription.service_type_id
            initial["plan"] = subscription.plan_id

            return initial

        servicio, plan = self.servicio_y_plan_por_defecto()

        if servicio is not None:
            initial["service_type"] = servicio

        if plan is not None:
            initial["plan"] = plan

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

    def next_contract_sequence(self):
        """Correlativo que le tocaria al proximo contrato.

        Lo usan el número que se guarda y el código que la pantalla muestra
        bloqueado, para que ATC vea de antemano el mismo valor que va a
        quedar registrado.
        """

        last_contract = (
            Contract.objects
            .order_by("-id")
            .first()
        )

        if last_contract is None:
            return 1

        return last_contract.id + 1

    def generate_contract_number(self):
        """
        Genera un número único de contrato.
        Formato: CONT-000001
        """

        return f"CONT-{self.next_contract_sequence():06d}"

    def etiqueta_de_la_suscripcion(self, form):
        """El código que se lee en el campo bloqueado de suscripción.

        Con el formulario enviado, el de la que `clean()` ya resolvió. Sin
        enviar, el de la que corresponde a los valores con los que abre la
        pantalla. El javascript lo vuelve a calcular con cada cambio de
        servicio o plan, leyendo el mismo catálogo y en el mismo orden.
        """

        if form.is_bound:
            subscription = getattr(form, "subscription_resuelta", None)

        else:
            subscription = self.get_preselected_subscription()

            if subscription is None:
                subscription = resolver_suscripcion(
                    self.customer,
                    form.initial.get("service_type"),
                    form.initial.get("plan"),
                )

        return codigo_de_suscripcion(subscription)

    def form_valid(self, form):

        try:

            with transaction.atomic():

                contract = form.save(commit=False)

                contract.customer = self.customer

                contract.contract_number = (
                    self.generate_contract_number()
                )

                # El estado no se toca: un contrato nuevo nace activo, y eso
                # lo dice el valor por defecto del modelo. Forzarlo aqui
                # tambien pondria la misma regla en dos sitios, y la pantalla
                # -que muestra el estado bloqueado- lee el del modelo.

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
        context["selected_subscription_id"] = (
            (self.request.POST.get("subscription_id") or "").strip()
            if self.request.method == "POST"
            else (
                context["preselected_subscription"].pk
                if context["preselected_subscription"] is not None
                else ""
            )
        )

        # Servicio y plan son un solo dato en dos combos: el catálogo entero
        # viaja con la página y el combo de planes se repinta sin recargar.
        # Es el mismo mecanismo del alta de suscripción.
        context["plans_by_service_type"] = plans_by_service_type()
        context["service_type_config"] = service_type_config()

        # Las suscripciones contratables del cliente, con el servicio y el
        # plan de cada una: el contrato exige que coincidan, así que el combo
        # solo ofrece las del plan elegido en vez de dejar que ATC descubra
        # la incompatibilidad al guardar.
        context["subscriptions_catalog"] = [
            {
                "id": subscription.pk,
                "label": codigo_de_suscripcion(subscription),
                "service_type": subscription.service_type_id,
                "plan": subscription.plan_id,
            }
            for subscription in suscripciones_contratables(self.customer)
        ]

        # La suscripción que le tocaría al contrato con lo que la pantalla
        # muestra ahora mismo. Va bloqueada: el operador la lee para saber
        # qué se está contratando, no la elige.
        context["resolved_subscription_label"] = (
            self.etiqueta_de_la_suscripcion(context["form"])
        )

        # Código y número los pone el sistema. Se muestran bloqueados para
        # que ATC reconozca la pantalla y sepa con qué número va a quedar el
        # contrato, no para escribirlos.
        context["next_contract_code"] = self.next_contract_sequence()
        context["next_contract_number"] = self.generate_contract_number()

        return context


class ContractSummaryView(LoginRequiredMixin, DetailView):
    """
El contrato registrado, de solo lectura.

    Muestra los mismos campos, en el mismo orden y con la misma
    disposición que la pantalla donde se registró: es un solo documento
    visto después, no otro.

    No ofrece la orden de instalación. El contrato es el documento
    comercial; la orden de trabajo es lo que se ejecuta en campo y se crea
    desde «Nueva orden de trabajo», la puerta común a todas las órdenes.
    `InstallationWorkOrderCreateView` sigue existiendo y sirviendo por su
    URL, con sus reglas intactas.
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
                "service_type",
                "plan",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        subscription = self.object.subscription

        context["customer"] = self.object.customer
        context["subscription"] = subscription

        # La suscripción se lee igual que en el alta: por su código. Es el
        # mismo documento visto después, no otro.
        context["subscription_label"] = codigo_de_suscripcion(subscription)

        # La firma que el abonado dibujó en campo. No se muestra el trazo
        # -para verlo está el documento, que es donde significa algo-, sino
        # si el contrato está firmado y desde qué orden se recogió: es lo que
        # ATC necesita saber sin abrir el PDF.
        context["signature"] = firma_del_contrato(self.object)

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
        Mismo criterio que `create_installation_work_order()`: una
        instalación que todavía no llegó a un estado final bloquea una
        nueva. Se comprueba aquí -y no solo en la fachada- para no ofrecer
        un formulario condenado a fallar al guardar.

        La pantalla del contrato ya no enlaza aquí, pero esta vista sigue
        sirviendo por su URL, así que la comprobación sigue haciendo falta.
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