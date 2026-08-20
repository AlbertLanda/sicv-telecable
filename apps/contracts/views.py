from multiprocessing import context

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView

from .forms import ContractCreateForm
from .models import Contract
from apps.customers.models import Customer


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

        return redirect(
            "customers:detail",
            pk=self.customer.pk,
        )

    def get_context_data(self, **kwargs):

        context = super().get_context_data(**kwargs)

        context["customer"] = self.customer

        context["return_to_general"] = (
            self.request.GET.get("return") == "general"
        )

        return context