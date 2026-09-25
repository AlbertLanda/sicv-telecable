from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.customers.models import Customer

from .catalog import plans_by_service_type, service_type_config
from .commercial import build_commercial_quote
from .forms import (
    PlanForm,
    ServiceTypeForm,
    SubscriptionCreateForm,
    SubscriptionSellerForm,
)
from .models import Plan, ServiceType, Subscription


def _commercial_quotes_for_customer(customer):
    """Matriz pequeña para que ATC vea la cotización antes de guardar."""
    matrix = {}
    addresses = (
        customer.addresses
        .filter(is_active=True)
        .select_related("zone", "zone__branch", "customer__branch")
    )
    plans = Plan.objects.filter(is_active=True).select_related("billing_policy")

    for address in addresses:
        matrix[str(address.pk)] = {}
        for plan in plans:
            try:
                quote = build_commercial_quote(plan=plan, address=address)
                policy = quote["billing_policy"]
                coverage = quote["coverage_rule"]
                matrix[str(address.pk)][str(plan.pk)] = {
                    "available": True,
                    "installation_fee": str(quote["installation_fee"]),
                    "monthly_fee": str(quote["monthly_fee"]),
                    "billing_policy": str(policy) if policy else "Sin política asignada",
                    "discount_amount": str(policy.discount_amount) if policy else "0.00",
                    "coverage": (
                        coverage.get_availability_display() if coverage else "Permitido"
                    ),
                }
            except ValidationError as exc:
                matrix[str(address.pk)][str(plan.pk)] = {
                    "available": False,
                    "message": " ".join(exc.messages),
                }
    return matrix


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
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["customer"] = self.customer
        kwargs["actor"] = self.request.user
        return kwargs

    def form_valid(self, form):
        try:
            with transaction.atomic():
                locked_customer = Customer.objects.select_for_update().get(pk=self.customer.pk)

                subscription = form.save(commit=False)
                subscription.customer = locked_customer
                subscription.registered_by = self.request.user
                subscription.status = Subscription.Status.PRESALE
                subscription.annex_count = form.calculated_annex_count
                subscription.initial_tv_courtesy_granted = (
                    form.calculated_initial_courtesy_count
                )

                quote = form.selected_quote or build_commercial_quote(
                    plan=subscription.plan,
                    address=subscription.address,
                )
                subscription.tariff = quote["tariff"]
                subscription.billing_policy = quote["billing_policy"]
                subscription.base_installation_fee = quote["installation_fee"]
                subscription.base_monthly_fee = quote["monthly_fee"]
                subscription.included_app_plan = (
                    subscription.plan.included_app_plan
                )
                subscription.included_app_component_amount = (
                    subscription.plan.included_app_component_amount
                    if subscription.plan.included_app_plan_id
                    else 0
                )

                if (
                    subscription.included_app_plan_id
                    and subscription.included_app_component_amount
                    >= subscription.base_monthly_fee
                ):
                    raise ValidationError(
                        "El componente APP configurado debe ser menor que "
                        "la mensualidad real aplicada a este domicilio."
                    )

                subscription.service_number = (
                    Subscription.next_service_number(
                        locked_customer,
                        subscription.service_type,
                    )
                )
                subscription.full_clean()
                subscription.save()
                self.object = subscription

        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
            return self.form_invalid(form)
        except IntegrityError:
            form.add_error(
                None,
                (
                    "No fue posible registrar la suscripción. Puede existir otro "
                    "servicio abierto del mismo tipo en ese domicilio. Actualice "
                    "la ficha y vuelva a intentarlo."
                ),
            )
            return self.form_invalid(form)

        messages.success(self.request, "Suscripción registrada correctamente.")
        return redirect(
            "services:subscription_summary",
            customer_pk=self.customer.pk,
            subscription_pk=subscription.pk,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["customer"] = self.customer
        context["plans_by_service_type"] = plans_by_service_type()
        context["service_type_config"] = service_type_config()
        context["commercial_quotes"] = _commercial_quotes_for_customer(self.customer)
        return context


class SubscriptionSellerUpdateView(LoginRequiredMixin, UpdateView):
    """Recupera altas antiguas que llegaron a Preventa sin vendedor."""

    model = Subscription
    form_class = SubscriptionSellerForm
    template_name = "services/subscription_seller_form.html"
    pk_url_kwarg = "subscription_pk"

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(
            Customer,
            pk=self.kwargs["customer_pk"],
            is_active=True,
        )

        subscription = get_object_or_404(
            Subscription.objects.select_related(
                "customer",
                "service_type",
                "plan",
                "address",
                "registered_by",
                "seller",
            ),
            pk=self.kwargs["subscription_pk"],
            customer=self.customer,
            is_active=True,
            status__in=(
                Subscription.Status.PRESALE,
                Subscription.Status.INSTALLATION,
            ),
        )

        if subscription.seller_id:
            messages.info(
                request,
                "La venta ya tiene vendedor identificado.",
            )
            return redirect(
                "services:subscription_summary",
                customer_pk=self.customer.pk,
                subscription_pk=subscription.pk,
            )

        self._subscription = subscription
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return (
            Subscription.objects
            .filter(
                customer=self.customer,
                is_active=True,
                status__in=(
                    Subscription.Status.PRESALE,
                    Subscription.Status.INSTALLATION,
                ),
            )
            .select_related(
                "customer",
                "service_type",
                "plan",
                "address",
                "registered_by",
            )
        )

    def get_object(self, queryset=None):
        if hasattr(self, "_subscription"):
            return self._subscription
        return super().get_object(queryset)

    def form_valid(self, form):
        seller = form.cleaned_data["seller"]

        try:
            with transaction.atomic():
                locked = (
                    Subscription.objects
                    .select_for_update()
                    .select_related("seller")
                    .get(pk=self.object.pk)
                )

                if locked.seller_id:
                    messages.info(
                        self.request,
                        "La venta ya tiene vendedor identificado.",
                    )
                else:
                    locked.seller = seller
                    locked.full_clean()
                    locked.save(update_fields=["seller", "updated_at"])
                    messages.success(
                        self.request,
                        (
                            f"Vendedor registrado: {seller}. "
                            "El alta ya puede continuar al contrato."
                        ),
                    )

                self.object = locked

        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
            return self.form_invalid(form)

        return redirect(
            "customers:detail",
            pk=self.customer.pk,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["customer"] = self.customer
        context["subscription"] = self.object
        return context


class SubscriptionSummaryView(LoginRequiredMixin, DetailView):
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
                "tariff",
                "billing_policy",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        subscription = self.object
        context["customer"] = subscription.customer
        context["existing_contract"] = (
            subscription.contracts.filter(is_active=True).first()
        )
        return context


# ---------------------------------------------------------------------
# Configurar > Planes y Servicios
#
# Hasta aquí el catálogo comercial solo se cargaba con
# `cargar_catalogo_comercial` o desde el admin de Django. Estas pantallas lo
# ponen en manos del área comercial: el comando sigue sirviendo para sembrar
# una instalación nueva, y el mantenimiento del día a día se hace acá.
# ---------------------------------------------------------------------


class ServiceTypeListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Los servicios que se pueden contratar."""

    model = ServiceType
    template_name = "services/servicetype_list.html"
    context_object_name = "service_types"
    permission_required = "services.view_servicetype"

    def get_queryset(self):
        return ServiceType.objects.annotate(
            plan_count=Count("plans", filter=Q(plans__is_active=True))
        ).order_by("code")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_edit"] = self.request.user.has_perm(
            "services.change_servicetype"
        )
        context["can_create"] = self.request.user.has_perm(
            "services.add_servicetype"
        )

        return context


class ServiceTypeCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = ServiceType
    form_class = ServiceTypeForm
    template_name = "services/servicetype_form.html"
    permission_required = "services.add_servicetype"
    success_url = reverse_lazy("services:servicetype_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request, f"Servicio «{self.object.name}» registrado."
        )

        return response


class ServiceTypeUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = ServiceType
    form_class = ServiceTypeForm
    template_name = "services/servicetype_form.html"
    permission_required = "services.change_servicetype"
    success_url = reverse_lazy("services:servicetype_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request, f"Servicio «{self.object.name}» actualizado."
        )

        return response


class PlanListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """
    Los planes del catálogo, con su precio normal y su precio de pronto pago.

    Se muestran las dos cifras porque son las dos que el abonado escucha en la
    venta. La de pronto pago no está guardada: se calcula con el descuento de
    la política del plan.
    """

    model = Plan
    template_name = "services/plan_list.html"
    context_object_name = "plans"
    permission_required = "services.view_plan"

    def get_queryset(self):
        queryset = Plan.objects.select_related(
            "service_type", "billing_policy"
        ).order_by("-generation", "service_type__code", "speed_mbps")

        service_code = self.request.GET.get("servicio")
        if service_code:
            queryset = queryset.filter(service_type__code=service_code)

        if self.request.GET.get("activos") == "1":
            queryset = queryset.filter(is_active=True)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["service_types"] = ServiceType.objects.order_by("code")
        context["current_service"] = self.request.GET.get("servicio", "")
        context["only_active"] = self.request.GET.get("activos") == "1"
        context["can_edit"] = self.request.user.has_perm("services.change_plan")
        context["can_create"] = self.request.user.has_perm("services.add_plan")

        return context


class PlanCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Plan
    form_class = PlanForm
    template_name = "services/plan_form.html"
    permission_required = "services.add_plan"
    success_url = reverse_lazy("services:plan_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Plan «{self.object.name}» registrado.")

        return response


class PlanUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Plan
    form_class = PlanForm
    template_name = "services/plan_form.html"
    permission_required = "services.change_plan"
    success_url = reverse_lazy("services:plan_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Plan «{self.object.name}» actualizado.")

        return response
