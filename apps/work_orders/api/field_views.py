"""Acciones API del técnico durante la ejecución de una Orden Técnica.

Complementa el MVP de Kevin (`available`, `claim`, `mis órdenes`, `detalle`)
con la ficha de campo creada por Joleydi. La entidad sigue siendo una sola
`WorkOrder`: después del claim el técnico inicia la atención, completa la
ficha y adjunta evidencias sobre esa misma orden.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.work_orders.api.field_serializers import (
    WorkOrderEvidenceSerializer,
    WorkOrderEvidenceUploadSerializer,
    WorkOrderFieldSheetSerializer,
    WorkOrderFieldSheetUpdateSerializer,
    WorkOrderStartSerializer,
)
from apps.work_orders.api.serializers import WorkOrderDetailSerializer
from apps.work_orders.api.views import TechnicianWorkOrderObjectMixin
from apps.work_orders.models import WorkOrder, WorkOrderFieldSheet
from apps.work_orders.services import (
    add_work_order_evidence,
    start_order_attention,
    update_field_sheet,
)


NOT_IN_PROGRESS_DETAIL = (
    "La ficha técnica solo puede modificarse cuando la orden está En atención."
)


def _django_validation_response(exc):
    return Response(
        {"detail": " ".join(exc.messages)},
        status=status.HTTP_400_BAD_REQUEST,
    )


class StartWorkOrderView(TechnicianWorkOrderObjectMixin, GenericAPIView):
    """POST `<id>/start/`: ASSIGNED/REPROGRAMMED -> IN_PROGRESS."""

    serializer_class = WorkOrderStartSerializer

    def post(self, request, *args, **kwargs):
        order = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            start_order_attention(
                order,
                user=request.user,
                remarks=serializer.validated_data["remarks"],
            )
        except DjangoValidationError as exc:
            return _django_validation_response(exc)

        order.refresh_from_db()
        return Response(WorkOrderDetailSerializer(order).data)


class FieldSheetView(TechnicianWorkOrderObjectMixin, GenericAPIView):
    """GET/PATCH `<id>/field-sheet/` sobre la misma WorkOrder."""

    serializer_class = WorkOrderFieldSheetUpdateSerializer

    @staticmethod
    def _sheet(order):
        try:
            return order.field_sheet
        except WorkOrder.field_sheet.RelatedObjectDoesNotExist:
            return WorkOrderFieldSheet(work_order=order)

    def get(self, request, *args, **kwargs):
        order = self.get_object()
        return Response(
            WorkOrderFieldSheetSerializer(self._sheet(order)).data
        )

    def patch(self, request, *args, **kwargs):
        order = self.get_object()

        # La toma (ASSIGNED) solo adjudica la OT. Los datos de campo empiezan
        # después de que el técnico declare formalmente el inicio.
        if order.status != WorkOrder.Status.IN_PROGRESS:
            return Response(
                {"detail": NOT_IN_PROGRESS_DETAIL},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sheet = update_field_sheet(
                order,
                user=request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as exc:
            return _django_validation_response(exc)

        return Response(WorkOrderFieldSheetSerializer(sheet).data)

    # POST se acepta como alias práctico para clientes móviles que no tengan
    # PATCH cómodo; la semántica sigue siendo actualización parcial.
    post = patch


class WorkOrderEvidenceListCreateView(
    TechnicianWorkOrderObjectMixin,
    GenericAPIView,
):
    """GET/POST `<id>/evidences/`: fotos/PDF de la atención en campo."""

    serializer_class = WorkOrderEvidenceUploadSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, *args, **kwargs):
        order = self.get_object()
        evidences = order.evidences.select_related("uploaded_by").all()
        return Response(
            WorkOrderEvidenceSerializer(
                evidences,
                many=True,
                context={"request": request},
            ).data
        )

    def post(self, request, *args, **kwargs):
        order = self.get_object()

        if order.status != WorkOrder.Status.IN_PROGRESS:
            return Response(
                {"detail": NOT_IN_PROGRESS_DETAIL},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            evidence = add_work_order_evidence(
                order,
                user=request.user,
                file=serializer.validated_data["file"],
                description=serializer.validated_data.get("description", ""),
            )
        except DjangoValidationError as exc:
            return _django_validation_response(exc)

        return Response(
            WorkOrderEvidenceSerializer(
                evidence,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )
