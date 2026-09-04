"""Acciones API del técnico durante la ejecución de una Orden Técnica."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.inventory.models import Material, WorkOrderMaterialMovement
from apps.inventory.services import (
    delete_work_order_material,
    record_work_order_material,
)
from apps.services.installation_rules import (
    record_installation_material_usage,
    total_installation_excess_charge,
)
from apps.work_orders.api.field_serializers import (
    InstallationMaterialUsageInputSerializer,
    InstallationMaterialUsageSerializer,
    MaterialCatalogSerializer,
    WorkOrderEvidenceSerializer,
    WorkOrderEvidenceUploadSerializer,
    WorkOrderFieldSheetSerializer,
    WorkOrderFieldSheetUpdateSerializer,
    WorkOrderMaterialMovementDeleteSerializer,
    WorkOrderMaterialMovementInputSerializer,
    WorkOrderMaterialMovementSerializer,
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
        try:
            sheet = update_field_sheet(
                order,
                user=request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as exc:
            return _django_validation_response(exc)
        return Response(WorkOrderFieldSheetSerializer(sheet).data)

    post = patch


class WorkOrderMaterialMovementView(
    TechnicianWorkOrderObjectMixin,
    GenericAPIView,
):
    """GET/POST/DELETE de materiales instalados y retirados en domicilio.

    Este registro es independiente del metraje que calcula excesos. Aquí se
    declara qué material o equipo entró/salió del domicilio y en qué cantidad;
    todavía no modifica stock ni kardex de almacén.
    """

    serializer_class = WorkOrderMaterialMovementInputSerializer

    @staticmethod
    def _payload(order):
        movements = (
            order.field_material_movements
            .select_related("material", "recorded_by")
            .all()
        )
        installed = [
            movement
            for movement in movements
            if movement.movement_type == WorkOrderMaterialMovement.MovementType.INSTALLED
        ]
        removed = [
            movement
            for movement in movements
            if movement.movement_type == WorkOrderMaterialMovement.MovementType.REMOVED
        ]
        catalog = Material.objects.filter(is_active=True).order_by("name")
        return {
            "catalog": MaterialCatalogSerializer(catalog, many=True).data,
            "installed": WorkOrderMaterialMovementSerializer(installed, many=True).data,
            "removed": WorkOrderMaterialMovementSerializer(removed, many=True).data,
        }

    def get(self, request, *args, **kwargs):
        order = self.get_object()
        return Response(self._payload(order))

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
            movement = record_work_order_material(
                work_order=order,
                user=request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as exc:
            return _django_validation_response(exc)

        return Response(
            {
                "item": WorkOrderMaterialMovementSerializer(movement).data,
                **self._payload(order),
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, *args, **kwargs):
        order = self.get_object()
        if order.status != WorkOrder.Status.IN_PROGRESS:
            return Response(
                {"detail": NOT_IN_PROGRESS_DETAIL},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = WorkOrderMaterialMovementDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        movement = get_object_or_404(
            WorkOrderMaterialMovement,
            pk=serializer.validated_data["movement_id"],
            work_order=order,
        )
        try:
            delete_work_order_material(
                work_order=order,
                movement=movement,
                user=request.user,
            )
        except DjangoValidationError as exc:
            return _django_validation_response(exc)

        return Response(self._payload(order), status=status.HTTP_200_OK)


class InstallationMaterialUsageListCreateView(
    TechnicianWorkOrderObjectMixin,
    GenericAPIView,
):
    """
    GET/POST `<id>/materials/`.

    El técnico registra metros realmente utilizados. El backend resuelve la
    regla vigente por material/servicio/sede y calcula exceso e importe; el
    cliente móvil nunca envía precios ni metros gratuitos.
    """

    serializer_class = InstallationMaterialUsageInputSerializer

    def get(self, request, *args, **kwargs):
        order = self.get_object()
        usages = order.installation_material_usages.select_related("rule").all()
        return Response(
            {
                "items": InstallationMaterialUsageSerializer(usages, many=True).data,
                "total_excess_charge": str(total_installation_excess_charge(order)),
            }
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
            usage = record_installation_material_usage(
                work_order=order,
                material=serializer.validated_data["material"],
                meters_used=serializer.validated_data["meters_used"],
            )
        except DjangoValidationError as exc:
            return _django_validation_response(exc)

        return Response(
            {
                "item": InstallationMaterialUsageSerializer(usage).data,
                "total_excess_charge": str(total_installation_excess_charge(order)),
            },
            status=status.HTTP_200_OK,
        )


class WorkOrderEvidenceListCreateView(
    TechnicianWorkOrderObjectMixin,
    GenericAPIView,
):
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
