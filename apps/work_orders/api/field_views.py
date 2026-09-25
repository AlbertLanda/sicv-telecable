"""Acciones API del técnico durante la ejecución de una Orden Técnica."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.models import User
from apps.inventory.models import Material, WorkOrderMaterialMovement
from apps.inventory.services import (
    delete_work_order_material,
    record_work_order_material,
)
from apps.technicians.models import TechnicianProfile
from apps.services.installation_rules import (
    record_installation_material_usage,
    total_installation_excess_charge,
)
from apps.work_orders.api.field_completion import (
    field_completion_summary,
    liquidation_items_from_field,
    liquidation_technical_data_from_field,
)
from apps.work_orders.api.field_serializers import (
    FaultResponsibilityEvidenceSerializer,
    FaultResponsibilityInputSerializer,
    InstallationMaterialUsageInputSerializer,
    InstallationMaterialUsageSerializer,
    MaterialCatalogSerializer,
    OrderResultSerializer,
    WorkOrderCompletionSerializer,
    WorkOrderEvidenceSerializer,
    WorkOrderEvidenceUploadSerializer,
    WorkOrderFieldSheetSerializer,
    WorkOrderFieldSheetUpdateSerializer,
    WorkOrderLiquidationInputSerializer,
    WorkOrderMaterialMovementDeleteSerializer,
    WorkOrderMaterialMovementInputSerializer,
    WorkOrderMaterialMovementSerializer,
    WorkOrderStartSerializer,
)
from apps.work_orders.api.serializers import WorkOrderDetailSerializer
from apps.work_orders.api.views import TechnicianWorkOrderObjectMixin
from apps.work_orders.faults import (
    fault_detail_for,
    set_fault_responsibility,
)
from apps.work_orders.models import (
    FaultDetail,
    OrderResult,
    WorkOrder,
    WorkOrderFieldSheet,
)
from apps.work_orders.services import (
    add_work_order_evidence,
    attend_order,
    liquidate_order,
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


def _completion_payload(order):
    results = OrderResult.objects.filter(
        order_type=order.order_type,
        is_active=True,
    ).order_by("name")

    expected_area = (
        TechnicianProfile.Area.PEX
        if order.is_outside_plant
        else TechnicianProfile.Area.INTERNAL_NETWORK
    )
    participant_options = (
        User.objects
        .filter(
            role=User.Role.TECHNICIAN,
            is_active=True,
            technician_profile__area=expected_area,
        )
        .order_by("first_name", "last_name", "username")
    )
    participants = (
        order.participations
        .select_related("user")
        .order_by("started_at", "pk")
    )

    return {
        "status": order.status,
        "status_display": order.get_status_display(),
        "results": OrderResultSerializer(results, many=True).data,
        "selected_result": (
            OrderResultSerializer(order.result).data
            if order.result_id
            else None
        ),
        "summary": field_completion_summary(order),
        "participant_options": [
            {
                "id": participant.pk,
                "display_name": str(participant),
            }
            for participant in participant_options
        ],
        "participants": [
            {
                "id": participation.user_id,
                "display_name": str(participation.user),
                "source": participation.get_source_display(),
            }
            for participation in participants
        ],
    }


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


class CompleteWorkOrderView(TechnicianWorkOrderObjectMixin, GenericAPIView):
    """Resumen de cierre y transición IN_PROGRESS -> ATTENDED."""

    serializer_class = WorkOrderCompletionSerializer

    def get(self, request, *args, **kwargs):
        return Response(_completion_payload(self.get_object()))

    def post(self, request, *args, **kwargs):
        order = self.get_object()
        if order.status != WorkOrder.Status.IN_PROGRESS:
            return Response(
                {"detail": "Solo una orden En atención puede finalizar su atención."},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.validated_data["result"]
        if result.order_type_id != order.order_type_id:
            return Response(
                {"detail": "El resultado seleccionado no corresponde al tipo de orden."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            attend_order(
                order,
                result=result,
                user=request.user,
                remarks=serializer.validated_data["remarks"],
            )
        except DjangoValidationError as exc:
            return _django_validation_response(exc)

        order.refresh_from_db()
        return Response(
            {
                "order": WorkOrderDetailSerializer(order).data,
                **_completion_payload(order),
            }
        )


class LiquidateWorkOrderView(TechnicianWorkOrderObjectMixin, GenericAPIView):
    """Consolida la atención ya finalizada y pasa ATTENDED -> LIQUIDATED."""

    serializer_class = WorkOrderLiquidationInputSerializer

    def post(self, request, *args, **kwargs):
        order = self.get_object()
        if order.status != WorkOrder.Status.ATTENDED:
            return Response(
                {"detail": "Solo una orden Atendida puede enviar su liquidación técnica."},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        technical_data = liquidation_technical_data_from_field(order)
        technical_notes = serializer.validated_data["technical_notes"]
        if not technical_notes:
            try:
                technical_notes = order.field_sheet.notes
            except WorkOrder.field_sheet.RelatedObjectDoesNotExist:
                technical_notes = ""

        try:
            liquidate_order(
                order,
                user=request.user,
                resolution_detail=serializer.validated_data["resolution_detail"],
                technical_notes=technical_notes,
                items=liquidation_items_from_field(order),
                remarks=serializer.validated_data["remarks"],
                participant_users=serializer.validated_data[
                    "participant_users"
                ],
                **technical_data,
            )
        except DjangoValidationError as exc:
            return _django_validation_response(exc)

        order.refresh_from_db()
        return Response(
            {
                "order": WorkOrderDetailSerializer(order).data,
                **_completion_payload(order),
            }
        )


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
    """GET/POST `<id>/materials/`: metraje real y exceso calculado."""

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


def _fault_responsibility_payload(order, request):
    """Lo que el portal necesita para mostrar y registrar la responsabilidad.

    No lleva montos: lo que se le cobre al cliente sale en su deuda, que
    arma caja con el material que la liquidación congela.
    """
    detail = fault_detail_for(order)
    evidences = (
        detail.evidences.select_related("uploaded_by").all()
        if detail.pk is not None
        else []
    )

    return {
        "responsibility": detail.responsibility,
        "responsibility_display": detail.get_responsibility_display(),
        "note": detail.responsibility_note,
        "is_registered": detail.pk is not None,
        "source": detail.responsibility_source if detail.pk else None,
        "source_display": (
            detail.get_responsibility_source_display() if detail.pk else None
        ),
        "set_by": (
            {
                "id": detail.responsibility_set_by_id,
                "display_name": str(detail.responsibility_set_by),
            }
            if detail.responsibility_set_by_id
            else None
        ),
        "set_at": detail.responsibility_set_at,
        "editable": order.status == WorkOrder.Status.IN_PROGRESS,
        "choices": [
            {"value": value, "label": label}
            for value, label in FaultDetail.Responsibility.choices
        ],
        "evidences": FaultResponsibilityEvidenceSerializer(
            evidences,
            many=True,
            context={"request": request},
        ).data,
    }


class FaultResponsibilityView(TechnicianWorkOrderObjectMixin, GenericAPIView):
    """GET/POST /api/technicians/work-orders/<id>/fault-responsibility/

    El técnico confirma o corrige quién causó la avería. Si es el cliente,
    sustenta por qué y puede adjuntar fotos o PDF; al finalizar la atención, el material
    instalado se le propone cobrar a los precios del catálogo.
    """

    serializer_class = FaultResponsibilityInputSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_fault_order(self):
        order = self.get_object()
        if not order.is_fault:
            raise NotFound("Esta orden no es una avería.")
        return order

    def get(self, request, *args, **kwargs):
        order = self.get_fault_order()
        return Response(_fault_responsibility_payload(order, request))

    def post(self, request, *args, **kwargs):
        order = self.get_fault_order()
        if order.status != WorkOrder.Status.IN_PROGRESS:
            return Response(
                {
                    "detail": (
                        "La responsabilidad solo puede registrarse cuando "
                        "la orden está En atención."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            set_fault_responsibility(
                order=order,
                user=request.user,
                responsibility=serializer.validated_data["responsibility"],
                note=serializer.validated_data.get("note", ""),
                evidence_files=serializer.validated_data.get("files", []),
            )
        except DjangoValidationError as exc:
            return _django_validation_response(exc)

        return Response(_fault_responsibility_payload(order, request))
