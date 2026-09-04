from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView, DetailView

from apps.customers.models import Customer

from .commercial import build_commercial_quote
from .forms import SubscriptionCreateForm
from .models import Plan, ServiceType, Subscription


def _plans_by_service_type():
    grouped = defaultdict(list)
    plans = (
        Plan.objects
        .filter(is_active=True)
        .select_related("billing_policy")
        .order_by("service_type_id", "-generation", "commercial_category", "speed_mbps", "name")
    )

    for plan in plans:
        grouped[plan.service_type_id].append(
            {
                "id": plan.pk,
                "label": str(plan),
                "generation": plan.generation,
                "category": plan.get_commercial_category_display() if plan.commercial_category else "",
                "initial_tv_courtesy_limit": plan.initial_tv_courtesy_limit,
                "monthly_price": str(plan.monthly_price),
                "requires_geographic_tariff": plan.requires_geographic_tariff,
                "billing_policy": str(plan.billing_policy) if plan.billing_policy_id else "",
            }
        )
    return dict(grouped)


def _service_type_config():
    return {
        service_type.pk: {
            "supports_tv_annexes": service_type.supports_tv_annexes,
            "annex_installation_price": str(service_type.annex_installation_price),
            "annex_monthly_price": str(service_type.annex_monthly_price),
        }
        for service_type in ServiceType.objects.filter(is_active=True)
    }


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
        return kwargs

    def form_valid(self, form):
        try:
            with transaction.atomic():
                locked_customer = Customer.objects.select_for_update().get(pk=self.customer.pk)

                subscription = form.save(commit=False)
                subscription.customer = locked_customer
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

                last_service_number = (
                    Subscription.objects
                    .filter(
                        customer=locked_customer,
                        service_type=subscription.service_type,
                    )
                    .aggregate(max_number=Max("service_number"))
                    .get("max_number")
                    or 0
                )
                subscription.service_number = last_service_number + 1
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
        context["plans_by_service_type"] = _plans_by_service_type()
        context["service_type_config"] = _service_type_config()
        context["commercial_quotes"] = _commercial_quotes_for_customer(self.customer)
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
