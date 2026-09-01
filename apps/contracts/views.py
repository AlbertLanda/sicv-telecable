from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView, DetailView

from .forms import ContractCreateForm
from .models import Contract
from apps.customers.models import Customer
from apps.services.models import Subscription


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
    registrados. No genera ninguna Orden de Trabajo: esa acción se
    habilita en una jornada posterior del sprint.
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

        context["customer"] = self.object.customer
        context["subscription"] = self.object.subscription

        return context