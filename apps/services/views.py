from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView, DetailView

from .forms import SubscriptionCreateForm
from .models import Plan, ServiceType, Subscription
from apps.customers.models import Customer


def _plans_by_service_type():
    """
    Agrupa los planes activos por tipo de servicio para alimentar el
    selector dinámico Servicio -> Plan del formulario de suscripción.
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
                "included_tv_points": plan.included_tv_points,
                "monthly_price": str(plan.monthly_price),
            }
        )

    return dict(grouped)


def _service_type_config():
    """Configuración comercial necesaria para la UI de anexos."""
    return {
        service_type.pk: {
            "supports_tv_annexes": service_type.supports_tv_annexes,
            "annex_installation_price": str(
                service_type.annex_installation_price
            ),
            "annex_monthly_price": str(service_type.annex_monthly_price),
        }
        for service_type in ServiceType.objects.filter(is_active=True)
    }


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
                # El correlativo de service_number deja de ser un dato manual
                # de ATC. Se bloquea el cliente para serializar dos altas
                # concurrentes del mismo abonado y se calcula el siguiente.
                locked_customer = Customer.objects.select_for_update().get(
                    pk=self.customer.pk,
                )

                subscription = form.save(commit=False)
                subscription.customer = locked_customer
                subscription.status = Subscription.Status.PRESALE
                subscription.annex_count = form.calculated_annex_count

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
            form.add_error(
                None,
                " ".join(exc.messages),
            )
            return self.form_invalid(form)

        except IntegrityError:
            form.add_error(
                None,
                (
                    "No fue posible registrar la suscripción. Puede existir "
                    "otro servicio abierto del mismo tipo en ese domicilio. "
                    "Actualice la ficha y vuelva a intentarlo."
                ),
            )
            return self.form_invalid(form)

        messages.success(
            self.request,
            "Suscripción registrada correctamente.",
        )

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

        return context


class SubscriptionSummaryView(LoginRequiredMixin, DetailView):
    """Resumen de la suscripción antes de generar el contrato."""

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
