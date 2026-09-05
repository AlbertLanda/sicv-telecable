"""Presentación imprimible de la orden tal como fue emitida.

La vista deliberately no muestra ficha técnica, evidencias ni liquidación. Su
propósito es separar claramente lo solicitado por ATC de lo registrado después
por el técnico en campo.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.views import View

from .models import WorkOrder


class WorkOrderInitialPrintView(LoginRequiredMixin, View):
    template_name = "work_orders/work_order_initial_print.html"

    def get_order(self):
        return get_object_or_404(
            WorkOrder.objects.select_related(
                "subscription",
                "subscription__customer",
                "subscription__address",
                "subscription__address__zone",
                "subscription__service_type",
                "subscription__plan",
                "order_type",
                "subtype",
                "reason",
                "branch",
                "zone",
                "seller",
                "created_by",
                "assigned_technician",
            ),
            pk=self.kwargs["pk"],
        )

    def get(self, request, *args, **kwargs):
        order = self.get_order()
        is_owner_technician = order.assigned_technician_id == request.user.pk

        if not (
            is_owner_technician
            or request.user.has_perm("work_orders.view_workorder")
        ):
            raise PermissionDenied(
                "No tiene autorización para consultar esta orden."
            )

        return render(
            request,
            self.template_name,
            {
                "order": order,
                "customer": order.subscription.customer,
                "subscription": order.subscription,
                "address": order.subscription.address,
                "auto_print": request.GET.get("print") == "1",
            },
        )
