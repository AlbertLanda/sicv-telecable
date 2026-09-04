"""
Vistas web del módulo de órdenes de trabajo.

Capa delgada: la vista resuelve el contexto (qué cliente se está atendiendo,
qué orden se despacha, qué usuario opera), entrega el formulario y delega la
operación en el dominio -create_work_order() para registrar,
assign_technician() para asignar, start_order_attention() para iniciar la
atención-. No construye WorkOrder, no genera correlativos, no cambia status a
mano y no duplica las reglas del dominio.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views import View
from django.views.generic import FormView, ListView

from apps.customers.models import Customer
from apps.services.models import Subscription
from apps.work_orders.forms import (
    WorkOrderAssignForm,
    WorkOrderCreateForm,
    WorkOrderDispatchFilterForm,
    WorkOrderEvidenceUploadForm,
    WorkOrderFieldSheetForm,
    WorkOrderStartAttentionForm,
)
from apps.work_orders.location import resolve_location_display
from apps.work_orders.models import WorkOrder
from apps.work_orders.services import (
    add_work_order_evidence,
    create_work_order,
    start_order_attention,
    update_field_sheet,
)
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin


class WorkOrderCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    FormView,
):
    permission_required = "work_orders.add_workorder"

    form_class = WorkOrderCreateForm
    template_name = "work_orders/work_order_create.html"
    """
    Registro web de una nueva orden de trabajo para un cliente.

    Decisiones deliberadas:

    - Es un FormView y no un CreateView: no debe existir un form.save() que
      persista la orden por fuera del servicio.
    - El cliente se resuelve desde la URL con get_object_or_404(). El
      navegador no envía a qué cliente pertenece la orden; solo elige entre
      las suscripciones que el formulario ya acotó a ese cliente.
    - created_by sale de request.user. No es un campo del formulario, así que
      no hay POST capaz de suplantarlo.
    - order_number no se recibe ni se calcula: lo emite el correlativo
      transaccional dentro de create_work_order().
    - Un ValidationError del servicio vuelve al formulario como error visible.
      Como el servicio es atómico, ese fallo no deja ni orden ni correlativo
      consumido.
    """

    form_class = WorkOrderCreateForm
    template_name = "work_orders/work_order_create.html"

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(
            Customer.objects.select_related("branch"),
            pk=self.kwargs["customer_pk"],
            is_active=True,
        )

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()

        kwargs["customer"] = self.customer

        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["customer"] = self.customer

        # Se consulta para poder avisar en pantalla cuando el cliente todavía
        # no tiene suscripciones: sin una suscripción no hay orden posible.
        context["has_subscriptions"] = (
            Subscription.objects
            .filter(customer=self.customer, is_active=True)
            .exists()
        )

        return context

    def form_valid(self, form):
        try:
            order = create_work_order(
                created_by=self.request.user,
                **form.service_arguments(),
            )

        except ValidationError as exc:
            # El servicio rechazó la operación. Los mensajes se devuelven al
            # formulario tal cual: ya están redactados para el operador.
            form.add_error(None, exc.messages)

            return self.form_invalid(form)

        # El mensaje incluye el número de orden y un enlace directo a su
        # ficha: el flujo comercial no debe obligar a buscarla de nuevo para
        # confirmar que quedó registrada. format_html escapa order_number y
        # el estado; el único HTML de confianza es el que escribe esta vista.
        messages.success(
            self.request,
            format_html(
                "Orden de trabajo <strong>{}</strong> registrada "
                "correctamente en estado {}. "
                '<a href="{}" class="alert-link">Ver ficha de la orden</a>.',
                order.order_number,
                order.get_status_display(),
                reverse("work_orders:detail", kwargs={"pk": order.pk}),
            ),
        )

        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse(
            "customers:detail",
            kwargs={"pk": self.customer.pk},
        )


class WorkOrderAssignView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    FormView,
):
    """
    Asignación web de una orden de trabajo a un técnico.

    Decisiones deliberadas:

    - El permiso es funcional y propio (assign_workorder). Despachar no es
      "editar una orden": conceder change_workorder para poder asignar
      habilitaría mucho más de lo necesario.
    - La orden se resuelve desde la URL, no desde el POST, y solo cuando el
      permiso ya fue verificado: quien no puede asignar recibe 403 sin llegar
      a averiguar si la orden existe.
    - La transición la ejecuta order.assign_technician(). La vista no toca
      status, no escribe assigned_technician y no crea el registro del
      historial: si el dominio rechaza, se muestra su mensaje tal cual.
    - assign_technician() ya es atómico: un fallo deja la orden con su estado
      y su técnico anteriores, sin asignaciones a medio abrir.
    """

    permission_required = "work_orders.assign_workorder"

    form_class = WorkOrderAssignForm
    template_name = "work_orders/work_order_assign.html"

    def get_work_order(self):
        """
        Orden bajo asignación, resuelta una sola vez por petición.

        No se resuelve en dispatch() a propósito: así el control de permiso
        de PermissionRequiredMixin corre antes que la búsqueda y un usuario
        sin permiso no puede usar los 404 para sondear qué órdenes existen.
        """
        if not hasattr(self, "_work_order"):
            self._work_order = get_object_or_404(
                WorkOrder.objects.select_related(
                    "subscription",
                    "subscription__customer",
                    "subscription__address",
                    "subscription__address__zone",
                    "subscription__service_type",
                    "subscription__plan",
                    "branch",
                    "zone",
                    "order_type",
                    "subtype",
                    "assigned_technician",
                ),
                pk=self.kwargs["pk"],
            )

        return self._work_order

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()

        kwargs["order"] = self.get_work_order()

        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        order = self.get_work_order()

        context["order"] = order
        context["customer"] = order.subscription.customer

        # El estado manda: si la orden ya no admite asignación se muestra el
        # contexto pero no se ofrece el envío. La regla se consulta al modelo,
        # no se reescribe aquí, y la comprobación real la sigue haciendo el
        # dominio en cada POST.
        context["can_be_assigned"] = order.can_be_assigned

        # Sin técnicos elegibles no hay despacho posible: se avisa en pantalla
        # en lugar de mostrar un selector vacío sin explicación.
        context["has_technicians"] = (
            context["form"].fields["assigned_technician"].queryset.exists()
        )

        return context

    def form_valid(self, form):
        order = self.get_work_order()

        try:
            order.assign_technician(
                technician=form.cleaned_data["assigned_technician"],
                assigned_by=self.request.user,
                remarks=form.cleaned_data.get("remarks", ""),
            )

        except ValidationError as exc:
            # El dominio rechazó la transición (estado no asignable, técnico
            # no elegible). La transacción ya revirtió lo que hubiera tocado;
            # se relee la orden para no pintar en pantalla datos que no
            # llegaron a persistirse.
            order.refresh_from_db()

            form.add_error(None, exc.messages)

            return self.form_invalid(form)

        messages.success(
            self.request,
            (
                f"Orden de trabajo {order.order_number} asignada a "
                f"{order.assigned_technician}. Estado actual: "
                f"{order.get_status_display()}."
            ),
        )

        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse(
            "customers:detail",
            kwargs={"pk": self.get_work_order().subscription.customer_id},
        )


class WorkOrderStartAttentionView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    FormView,
):
    """
    Inicio web de la atención de una orden ya despachada.

    Es la pantalla de confirmación del paso ASSIGNED -> IN_PROGRESS: muestra
    contra qué orden se va a operar y ejecuta la transición por POST.

    Decisiones deliberadas:

    - El permiso es funcional y propio (start_workorder). Iniciar la atención
      no es despachar: assign_workorder decide a quién le toca la orden, y
      start_workorder declara que la atención empezó de verdad. Separarlos
      permite que la futura app/PWA del técnico reciba solo el segundo.
    - La operación la ejecuta start_order_attention(), el servicio del módulo,
      que internamente llama a WorkOrder.start_attention() y además mantiene
      coherente la suscripción -una instalación en preventa pasa a
      instalación-. La vista no reimplementa ninguna de las dos cosas: llamar
      al modelo directamente dejaría a la suscripción sin ese efecto.
    - La vista no conoce la matriz de estados. No comprueba si la orden es
      iniciable antes de operar: lo intenta y deja que el dominio acepte o
      rechace. can_start_attention solo decide si se pinta el botón.
    - El formulario únicamente lleva la observación. started_at, el estado
      destino y el técnico no son campos, así que no hay POST capaz de
      forzarlos: la hora la pone timezone.now() dentro del dominio.
    - La orden se resuelve desde la URL y solo después del control de
      permiso, igual que en la asignación: quien no puede iniciar recibe 403
      sin poder usar los 404 para sondear qué órdenes existen.
    - Un GET nunca cambia estado: FormView solo renderiza. La transición vive
      en form_valid(), que únicamente corre por POST.
    """

    permission_required = "work_orders.start_workorder"

    form_class = WorkOrderStartAttentionForm
    template_name = "work_orders/work_order_start_attention.html"

    def get_work_order(self):
        """Orden a iniciar, resuelta una sola vez por petición."""
        if not hasattr(self, "_work_order"):
            self._work_order = get_object_or_404(
                WorkOrder.objects.select_related(
                    "subscription",
                    "subscription__customer",
                    "subscription__address",
                    "subscription__address__zone",
                    "subscription__service_type",
                    "subscription__plan",
                    "branch",
                    "zone",
                    "order_type",
                    "subtype",
                    "assigned_technician",
                ),
                pk=self.kwargs["pk"],
            )

        return self._work_order

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        order = self.get_work_order()

        context["order"] = order
        context["customer"] = order.subscription.customer

        # Si la orden no admite inicio se muestra el contexto pero no se
        # ofrece el envío. La regla se consulta al modelo, no se reescribe
        # aquí, y la comprobación real la sigue haciendo el dominio.
        context["can_start_attention"] = order.can_start_attention

        # Cuál de las dos condiciones falló, para explicar en pantalla la
        # razón correcta. Se lee la misma lista del dominio que consulta
        # can_start_attention: no es una matriz de estados propia.
        context["is_startable_status"] = (
            order.status in WorkOrder.STARTABLE_STATUSES
        )

        return context

    def form_valid(self, form):
        order = self.get_work_order()

        try:
            start_order_attention(
                order,
                user=self.request.user,
                remarks=form.cleaned_data.get("remarks", ""),
            )

        except ValidationError as exc:
            # El dominio rechazó el inicio (estado no iniciable, orden sin
            # técnico). El servicio es atómico: no quedó ni started_at ni
            # historial a medias. Se relee la orden para no pintar en
            # pantalla datos que no llegaron a persistirse, y el mensaje del
            # dominio se muestra tal cual: ya está redactado para el operador
            # y no expone trazas internas.
            order.refresh_from_db()

            form.add_error(None, exc.messages)

            return self.form_invalid(form)

        messages.success(
            self.request,
            (
                f"Atención de la orden {order.order_number} iniciada. "
                f"Estado actual: {order.get_status_display()}. "
                f"Inicio registrado: "
                f"{timezone.localtime(order.started_at):%d/%m/%Y %H:%M}."
            ),
        )

        return redirect(self.get_success_url())

    def get_success_url(self):
        """
        Vuelta a la bandeja de despacho, que es de donde se lanza la acción.

        Quien puede iniciar una atención no necesariamente puede ver la
        bandeja -son permisos distintos-, así que sin view_workorder se
        redirige a la ficha del cliente, que solo exige estar autenticado.
        Redirigir a una pantalla prohibida convertiría un éxito en un 403.
        """
        if self.request.user.has_perm("work_orders.view_workorder"):
            return reverse("work_orders:dispatch")

        return reverse(
            "customers:detail",
            kwargs={"pk": self.get_work_order().subscription.customer_id},
        )


class WorkOrderDispatchListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    ListView,
):
    """
    Bandeja operativa de despacho de órdenes de trabajo.

    Es el paso entre el registro de la OT por ATC y su despacho a un técnico:
    lista, busca y filtra, y desde ahí enlaza al flujo de asignación que ya
    existe.

    Decisiones deliberadas:

    - Es una vista de solo lectura. No crea órdenes, no cambia estados y no
      asigna: la acción Asignar/Reasignar es un enlace a work_orders:assign,
      que es quien ejecuta la transición contra el dominio.
    - El permiso de visualización es view_workorder, el permiso por defecto
      de Django sobre el modelo. No se hardcodea ningún rol en la vista y no
      hace falta migración para declararlo.
    - Ver la bandeja y despachar son atribuciones distintas: view_workorder
      abre el listado, assign_workorder habilita la acción. Un usuario puede
      tener la primera sin la segunda.
    - Los filtros se validan en WorkOrderDispatchFilterForm, no aquí. La vista
      no interpreta parámetros crudos de la URL ni arma consultas a mano.
    - sede y zona filtran el listado y nada más. WorkOrderAssignForm no se
      toca: un técnico activo de otra sede sigue siendo elegible para una
      orden de cualquier sede.
    """

    permission_required = "work_orders.view_workorder"

    model = WorkOrder
    template_name = "work_orders/work_order_dispatch.html"
    context_object_name = "orders"
    paginate_by = 20

    def get_filter_form(self):
        """Formulario de filtros, enlazado a la query string de la petición."""
        if not hasattr(self, "_filter_form"):
            self._filter_form = WorkOrderDispatchFilterForm(
                data=self.request.GET,
            )

        return self._filter_form

    def get_queryset(self):
        queryset = (
            WorkOrder.objects
            # Todo lo que la tabla pinta por fila se trae en la misma consulta.
            # Sin esto, listar 20 órdenes dispara una consulta por cliente,
            # sede, zona, tipo y técnico de cada fila.
            .select_related(
                "subscription",
                "subscription__customer",
                "subscription__address",
                "subscription__address__zone",
                "branch",
                "zone",
                "order_type",
                "subtype",
                "assigned_technician",
                "assigned_technician__branch",
            )
            # Meta.ordering ya ordena por -created_at. Se repite aquí con un
            # desempate explícito por -pk porque la paginación lo necesita:
            # con dos órdenes creadas en el mismo instante, un orden no
            # determinista puede repetir o saltar filas entre páginas.
            .order_by("-created_at", "-pk")
        )

        return self.get_filter_form().apply_to(queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["filter_form"] = self.get_filter_form()

        # Los filtros deben sobrevivir a la paginación: se reenvía la query
        # string sin el parámetro de página, que cada enlace pone por su
        # cuenta.
        parameters = self.request.GET.copy()
        parameters.pop("page", None)

        context["querystring"] = parameters.urlencode()

        # Cuántas órdenes coinciden en total, no cuántas caben en la página.
        context["total_count"] = (
            context["paginator"].count
            if context.get("paginator")
            else len(context["orders"])
        )

        # Marca si hay algún filtro aplicado, para distinguir en pantalla
        # "no hay órdenes todavía" de "ningún resultado para esta búsqueda".
        context["has_filters"] = bool(context["querystring"])

        return context


class WorkOrderDetailView(LoginRequiredMixin, View):
    """
    Ficha única de una orden de trabajo.

    Sirve tanto a ATC/supervisión como al técnico asignado desde la misma
    plantilla: quien tiene el permiso funcional work_orders.view_workorder
    consulta en solo lectura -no se ofrece ningún control de edición de
    campos técnicos-, y el técnico asignado a ESTA orden en concreto además
    puede completar su ficha técnica de campo (NAP, borne, MAC/equipo,
    precinto, observaciones) y adjuntar evidencias, mientras la orden siga
    abierta. Ninguna de las dos condiciones habilita la otra: un técnico sin
    view_workorder solo abre las órdenes que tiene asignadas.

    A diferencia de WorkOrderAssignView/WorkOrderStartAttentionView, aquí la
    autorización depende del propio registro -si el usuario autenticado es
    el técnico asignado a esta orden en particular-, así que no puede
    resolverse con un permiso declarativo antes de la búsqueda: la orden se
    resuelve primero y el control de acceso se aplica sobre ella. Sigue
    habiendo LoginRequiredMixin delante: un anónimo nunca llega a la
    resolución de la orden, solo se redirige al login.

    La escritura (ficha técnica, evidencias) no ocurre en esta vista: se
    delega en services.update_field_sheet() y
    services.add_work_order_evidence(), que son quienes deciden si el
    usuario puede operar sobre la orden y dejan la comprobación real del
    lado del dominio, no del formulario.
    """

    template_name = "work_orders/work_order_detail.html"

    def get_work_order(self):
        """Orden de la ficha, resuelta una sola vez por petición."""
        if not hasattr(self, "_work_order"):
            self._work_order = get_object_or_404(
                WorkOrder.objects.select_related(
                    "subscription",
                    "subscription__customer",
                    "subscription__address",
                    "subscription__address__zone",
                    "subscription__service_type",
                    "subscription__plan",
                    "branch",
                    "zone",
                    "order_type",
                    "subtype",
                    "reason",
                    "cause",
                    "result",
                    "assigned_technician",
                    "created_by",
                ),
                pk=self.kwargs["pk"],
            )

        return self._work_order

    def _resolve_access(self, request, order):
        """
        Decide si el usuario puede ver esta orden y si además puede editar
        su ficha técnica. Deja el resultado en la instancia y corta con
        PermissionDenied si ninguna de las dos vías de acceso aplica.
        """
        user = request.user

        is_owner_technician = order.assigned_technician_id == user.pk
        can_view_as_staff = user.has_perm("work_orders.view_workorder")

        if not (is_owner_technician or can_view_as_staff):
            raise PermissionDenied(
                "No tiene autorización para consultar esta orden."
            )

        self.is_owner_technician = is_owner_technician

        # Ver como técnico propietario habilita edición solo mientras la
        # orden sigue operativamente abierta. La comprobación real -y la
        # única que importa de verdad- la repite el servicio en cada POST;
        # esto únicamente decide si se ofrecen los controles en pantalla.
        self.can_edit = is_owner_technician and not order.is_closed

    @staticmethod
    def _get_liquidation(order):
        try:
            return order.liquidation
        except WorkOrder.liquidation.RelatedObjectDoesNotExist:
            return None

    @staticmethod
    def _get_field_sheet(order):
        try:
            return order.field_sheet
        except WorkOrder.field_sheet.RelatedObjectDoesNotExist:
            return None

    def get_context(self, order, field_sheet_form, evidence_form):
        liquidation = self._get_liquidation(order)

        return {
            "order": order,
            "customer": order.subscription.customer,
            "subscription": order.subscription,
            "location": resolve_location_display(order.subscription.address),
            "liquidation": liquidation,
            "liquidation_items": (
                liquidation.items.all() if liquidation is not None else []
            ),
            "field_sheet": self._get_field_sheet(order),
            "evidences": order.evidences.select_related("uploaded_by").all(),
            "is_owner_technician": self.is_owner_technician,
            "can_edit": self.can_edit,
            "field_sheet_form": field_sheet_form,
            "evidence_form": evidence_form,
        }

    def get(self, request, *args, **kwargs):
        order = self.get_work_order()
        self._resolve_access(request, order)

        context = self.get_context(
            order,
            field_sheet_form=WorkOrderFieldSheetForm(
                instance=self._get_field_sheet(order),
            ),
            evidence_form=WorkOrderEvidenceUploadForm(),
        )

        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        order = self.get_work_order()
        self._resolve_access(request, order)

        if not self.can_edit:
            # ATC nunca envía este formulario -la plantilla no se lo
            # ofrece-, y un técnico ya no editor solo llega aquí forzando el
            # POST a mano. En ambos casos la respuesta es la misma: 403.
            raise PermissionDenied(
                "Esta orden no admite edición de su ficha técnica."
            )

        action = request.POST.get("action")

        if action == "save_field_sheet":
            return self._handle_field_sheet(request, order)

        if action == "upload_evidence":
            return self._handle_evidence_upload(request, order)

        raise PermissionDenied("Acción no reconocida.")

    def _handle_field_sheet(self, request, order):
        form = WorkOrderFieldSheetForm(
            request.POST,
            instance=self._get_field_sheet(order),
        )

        if form.is_valid():
            try:
                update_field_sheet(
                    order,
                    user=request.user,
                    **{
                        field: form.cleaned_data[field]
                        for field in WorkOrderFieldSheetForm.Meta.fields
                    },
                )

            except ValidationError as exc:
                # El dominio rechazó la escritura (orden cerrada entre el
                # GET y el POST, por ejemplo). Se relee la orden más abajo
                # para no pintar en pantalla datos que no llegaron a
                # persistirse.
                form.add_error(None, exc.messages)

            else:
                messages.success(
                    request,
                    "Ficha técnica de campo actualizada correctamente.",
                )

                return redirect("work_orders:detail", pk=order.pk)

        context = self.get_context(
            order,
            field_sheet_form=form,
            evidence_form=WorkOrderEvidenceUploadForm(),
        )

        return render(request, self.template_name, context)

    def _handle_evidence_upload(self, request, order):
        form = WorkOrderEvidenceUploadForm(request.POST, request.FILES)

        if form.is_valid():
            try:
                add_work_order_evidence(
                    order,
                    user=request.user,
                    file=form.cleaned_data["file"],
                    description=form.cleaned_data.get("description", ""),
                )

            except ValidationError as exc:
                form.add_error(None, exc.messages)

            else:
                messages.success(
                    request,
                    "Evidencia adjuntada correctamente.",
                )

                return redirect("work_orders:detail", pk=order.pk)

        context = self.get_context(
            order,
            field_sheet_form=WorkOrderFieldSheetForm(
                instance=self._get_field_sheet(order),
            ),
            evidence_form=form,
        )

        return render(request, self.template_name, context)
