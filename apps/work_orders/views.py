"""
Vistas web del módulo de órdenes de trabajo.

Capa delgada: la vista resuelve el contexto (qué cliente se está atendiendo,
qué orden se despacha, qué usuario opera), entrega el formulario y delega la
operación en el dominio -create_work_order() para registrar,
assign_technician() para asignar-. No construye WorkOrder, no genera
correlativos, no cambia status a mano y no duplica las reglas del dominio.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import FormView

from apps.customers.models import Customer
from apps.services.models import Subscription
from apps.work_orders.forms import WorkOrderAssignForm, WorkOrderCreateForm
from apps.work_orders.models import WorkOrder
from apps.work_orders.services import create_work_order
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

        messages.success(
            self.request,
            (
                f"Orden de trabajo {order.order_number} registrada "
                f"correctamente en estado {order.get_status_display()}."
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
