from django.db.models import Q, Prefetch
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import Customer, CustomerAddress
from apps.services.models import Subscription
from apps.contracts.models import Contract
from apps.work_orders.models import WorkOrder


class CustomerSearchView(LoginRequiredMixin, ListView):
    model = Customer
    template_name = "customers/search.html"
    context_object_name = "customers"
    paginate_by = 20

    def get_queryset(self):
        q = self.request.GET.get("q", "").strip()

        if not q:
            return Customer.objects.none()

        terms = q.split()

        query = Q()

        for term in terms:
            term_query = (
                Q(code__iexact=term)
                | Q(document_number__iexact=term)
                | Q(first_name__icontains=term)
                | Q(paternal_surname__icontains=term)
                | Q(maternal_surname__icontains=term)
                | Q(business_name__icontains=term)
                | Q(phone__icontains=term)
                | Q(secondary_phone__icontains=term)
            )

            query &= term_query

        return (
            Customer.objects
            .filter(query)
            .select_related("branch")
            .order_by(
                "paternal_surname",
                "maternal_surname",
                "first_name",
                "business_name",
            )
            .distinct()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["current_query"] = (
            self.request.GET.get("q", "").strip()
        )

        return context


class CustomerDetailView(LoginRequiredMixin, DetailView):
    model = Customer
    template_name = "customers/detail.html"
    context_object_name = "customer"

    def get_queryset(self):
        address_queryset = (
            CustomerAddress.objects
            .select_related("zone")
            .order_by("-is_primary", "address")
        )

        work_order_queryset = (
            WorkOrder.objects
            .select_related(
                "order_type",
                "subtype",
                "reason",
                "cause",
                "result",
                "assigned_technician",
                "branch",
                "zone",
            )
            .order_by("-created_at")
        )

        subscription_queryset = (
            Subscription.objects
            .select_related(
                "service_type",
                "plan",
                "address",
            )
            .prefetch_related(
                Prefetch(
                    "work_orders",
                    queryset=work_order_queryset,
                ),
                "contracts",
            )
            .order_by("-created_at")
        )

        contract_queryset = (
            Contract.objects
            .select_related(
                "subscription",
                "subscription__service_type",
                "subscription__plan",
            )
            .order_by("-created_at")
        )

        return (
            Customer.objects
            .select_related("branch")
            .prefetch_related(
                Prefetch(
                    "addresses",
                    queryset=address_queryset,
                ),
                Prefetch(
                    "subscriptions",
                    queryset=subscription_queryset,
                ),
                Prefetch(
                    "contracts",
                    queryset=contract_queryset,
                ),
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        customer = self.object

        context["addresses"] = customer.addresses.all()
        context["subscriptions"] = customer.subscriptions.all()
        context["contracts"] = customer.contracts.all()

        context["work_orders"] = (
            WorkOrder.objects
            .filter(subscription__customer=customer)
            .select_related(
                "subscription",
                "order_type",
                "subtype",
                "reason",
                "cause",
                "result",
                "branch",
                "zone",
                "assigned_technician",
            )
            .order_by("-created_at")
        )

        return context