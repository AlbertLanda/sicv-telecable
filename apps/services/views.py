from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView, DetailView

from .forms import SubscriptionCreateForm
from .models import Plan, Subscription
from apps.customers.models import Customer


def _plans_by_service_type():
    """
    Agrupa los planes activos por tipo de servicio para alimentar el
    selector dinámico Servicio -> Plan del formulario de suscripción.

    No reemplaza la validación de servidor ya existente en
    SubscriptionCreateForm.clean() (que sigue siendo la fuente de
    verdad); es solo un apoyo de UI para que el operador no pueda
    dejar seleccionada, en pantalla, una combinación Servicio/Plan que
    el servidor de todas formas va a rechazar.
    """

    grouped = defaultdict(list)

    plans = (
        Plan.objects
        .filter(is_active=True)
        .order_by("service_type_id", "name")
    )

    for plan in plans:
        grouped[plan.service_type_id].append(
            {
                "id": plan.pk,
                "label": str(plan),
            }
        )

    return dict(grouped)


class SubscriptionCreateView(LoginRequiredMixin, CreateView):
    model = Subscription
    form_class = SubscriptionCreateForm
    template_name = "services/subscription_create.html"

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

    def form_valid(self, form):
        try:
            with transaction.atomic():

                subscription = form.save(commit=False)

                subscription.customer = self.customer
                subscription.status = Subscription.Status.PRESALE

                subscription.save()

                self.object = subscription

        except IntegrityError:

            form.add_error(
                None,
                (
                    "No fue posible registrar la suscripción. "
                    "Verifique los datos e inténtelo nuevamente."
                ),
            )

            return self.form_invalid(form)

        messages.success(
            self.request,
            "Suscripción registrada correctamente.",
        )

        # -----------------------------------------------------------
        # RESUMEN PREVIO A LA CONTRATACIÓN
        #
        # En lugar de volver directo a la ficha del cliente, el
        # alta comercial FTTH continúa hacia una pantalla de resumen
        # que confirma cliente + domicilio + servicio/plan antes de
        # ofrecer la generación del contrato. Todavía no se toca
        # WorkOrder ni se genera ninguna OT en este punto del flujo.
        # -----------------------------------------------------------

        return redirect(
            "services:subscription_summary",
            customer_pk=self.customer.pk,
            subscription_pk=subscription.pk,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["customer"] = self.customer
        context["plans_by_service_type"] = _plans_by_service_type()

        return context


class SubscriptionSummaryView(LoginRequiredMixin, DetailView):
    """
    Resumen previo a la contratación (día 02/09 del sprint FTTH).

    Muestra, de solo lectura, los datos consolidados de la
    suscripción recién registrada (cliente, domicilio, servicio y
    plan) antes de avanzar a la generación del contrato. No crea ni
    modifica ningún registro.
    """

    model = Subscription
    template_name = "services/subscription_summary.html"
    context_object_name = "subscription"
    pk_url_kwarg = "subscription_pk"

    def get_queryset(self):
        return (
            Subscription.objects
            .filter(customer_id=self.kwargs["customer_pk"])
            .select_related(
                "customer",
                "address",
                "address__zone",
                "service_type",
                "plan",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        subscription = self.object

        context["customer"] = subscription.customer

        context["existing_contract"] = (
            subscription.contracts
            .filter(is_active=True)
            .first()
        )

        return context