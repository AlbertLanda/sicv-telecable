from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView

from .forms import SubscriptionCreateForm
from .models import Subscription
from apps.customers.models import Customer


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

        return redirect(
            "customers:detail",
            pk=self.customer.pk,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["customer"] = self.customer

        return context