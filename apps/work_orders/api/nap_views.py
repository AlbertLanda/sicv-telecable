"""Búsqueda y validación de NAP para el canal técnico."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from apps.work_orders.api.field_serializers import (
    WorkOrderFieldSheetSerializer,
    WorkOrderFieldSheetUpdateSerializer,
)
from apps.work_orders.api.field_views import (
    NOT_IN_PROGRESS_DETAIL,
    _django_validation_response,
)
from apps.work_orders.api.views import TechnicianWorkOrderObjectMixin
from apps.work_orders.models import WorkOrder, WorkOrderFieldSheet
from apps.work_orders.nap_catalog import NetworkAccessPoint
from apps.work_orders.services import update_field_sheet


class NetworkAccessPointSearchView(TechnicianWorkOrderObjectMixin, GenericAPIView):
    """Busca NAP activas exclusivamente dentro de la sede de la OT propia."""

    def get(self, request, *args, **kwargs):
        order = self.get_object()
        base = NetworkAccessPoint.objects.filter(
            branch=order.branch,
            is_active=True,
        )
        enabled = base.exists()
        query = (request.query_params.get("q") or "").strip()

        if len(query) < 2:
            return Response({"catalog_enabled": enabled, "results": []})

        matches = (
            base.filter(Q(code__icontains=query) | Q(name__icontains=query))
            .order_by("name")[:25]
        )
        return Response(
            {
                "catalog_enabled": enabled,
                "results": [
                    {
                        "id": nap.pk,
                        "legacy_id": nap.legacy_id,
                        "code": nap.code,
                        "name": nap.name,
                    }
                    for nap in matches
                ],
            }
        )


class CatalogFieldSheetView(TechnicianWorkOrderObjectMixin, GenericAPIView):
    """Ficha técnica con NAP validada contra catálogo cuando la sede ya lo tiene."""

    serializer_class = WorkOrderFieldSheetUpdateSerializer

    @staticmethod
    def _sheet(order):
        try:
            return order.field_sheet
        except WorkOrder.field_sheet.RelatedObjectDoesNotExist:
            return WorkOrderFieldSheet(work_order=order)

    def get(self, request, *args, **kwargs):
        order = self.get_object()
        return Response(WorkOrderFieldSheetSerializer(self._sheet(order)).data)

    def patch(self, request, *args, **kwargs):
        order = self.get_object()
        if order.status != WorkOrder.Status.IN_PROGRESS:
            return Response(
                {"detail": NOT_IN_PROGRESS_DETAIL},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        if "nap" in data:
            incoming_nap = (data.get("nap") or "").strip()
            current_nap = (self._sheet(order).nap or "").strip()
            catalog = NetworkAccessPoint.objects.filter(
                branch=order.branch,
                is_active=True,
            )

            # Despliegue progresivo por sede: donde todavía no se importó un
            # catálogo se conserva temporalmente el comportamiento legado.
            # En cuanto exista al menos una NAP activa, cualquier cambio debe
            # corresponder exactamente a una opción del catálogo.
            if catalog.exists() and incoming_nap != current_nap:
                if incoming_nap:
                    selected = catalog.filter(name=incoming_nap).first()
                    if selected is None:
                        return Response(
                            {
                                "nap": [
                                    "Seleccione una NAP válida del catálogo de esta sede."
                                ]
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    data["nap"] = selected.name
                else:
                    data["nap"] = ""

        try:
            sheet = update_field_sheet(
                order,
                user=request.user,
                **data,
            )
        except DjangoValidationError as exc:
            return _django_validation_response(exc)

        return Response(WorkOrderFieldSheetSerializer(sheet).data)

    post = patch
