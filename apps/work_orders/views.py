from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView

from apps.customers.models import Customer
from apps.organization.models import Branch, Zone

from .forms import WorkOrderCreateForm
from .models import WorkOrder


class WorkOrderCreateView(LoginRequiredMixin, CreateView):

    model = WorkOrder
    form_class = WorkOrderCreateForm
    template_name = "work_orders/order_create.html"

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

    def generate_order_number(self):

        last_order = (
            WorkOrder.objects
            .order_by("-id")
            .first()
        )

        if last_order is None:
            next_number = 1
        else:
            next_number = last_order.id + 1

        return f"OT-{next_number:06d}"

    def form_valid(self, form):

        try:

            with transaction.atomic():

                order = form.save(commit=False)

                order.order_number = (
                    self.generate_order_number()
                )

                order.created_by = self.request.user

                order.status = WorkOrder.Status.PENDING

                order.save()

                self.object = order

        except IntegrityError:

            form.add_error(
                None,
                (
                    "No fue posible registrar la orden. "
                    "Verifique los datos e inténtelo nuevamente."
                ),
            )

            return self.form_invalid(form)

        messages.success(
            self.request,
            (
                "Orden de trabajo registrada correctamente. "
                f"Número: {self.object.order_number}"
            ),
        )

        return redirect(
            "customers:detail",
            pk=self.customer.pk,
        )

    def get_context_data(self, **kwargs):

        context = super().get_context_data(**kwargs)

        context["customer"] = self.customer

        return context