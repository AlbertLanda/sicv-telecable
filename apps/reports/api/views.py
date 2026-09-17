"""El feed de movimientos de material para el sistema de logística.

Tres endpoints y tres preguntas distintas:

    GET /api/logistics/material-movements/          el detalle del periodo
    GET /api/logistics/material-movements/ids/      qué sigue existiendo
    GET /api/logistics/material-movements/watermark/ hasta dónde sincronizar

El primero entrega **el detalle, no el agregado**. Logística tabula por
técnico del otro lado -es lo que hoy hace a mano con una tabla dinámica sobre
el Excel- y ese total tiene que poder abrirse: cuando el cuadre de mochila no
cierra por unos metros de fibra, alguien tiene que llegar a las órdenes que lo
componen. Un endpoint que devolviera el total ya sumado convertiría esa
pregunta en una llamada telefónica.

El segundo existe por los borrados. Un técnico puede retirar un material que
declaró por error (`inventory.services.delete_work_order_material`), y una
sincronización que solo trae altas y cambios no se entera nunca: la fila
sobrevive en logística descontando stock que volvió al almacén. Devolviendo
los ids vigentes de un periodo, el otro sistema borra lo que le sobra. Esta
consulta siempre debe ser completa para el periodo: una lista incremental de
ids no sirve para reconciliar borrados.

Ninguno consulta la base por su cuenta: todos parten de
`materials.material_movements()`, el mismo queryset que imprime la hoja en
pantalla. Es lo que garantiza que el reporte y el cuadre den el mismo número.
"""

from django.db.models import DateTimeField, F, Max
from django.db.models.functions import Coalesce, Greatest
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.reports.materials import material_movements

from .forms import MaterialMovementQueryForm
from .pagination import MaterialMovementPagination
from .permissions import CanReadMaterialMovements
from .serializers import MaterialMovementSerializer


MAX_RECONCILIATION_IDS = 100_000


def _consultar(request):
    """Valida parámetros y arma el queryset común del canal de logística."""
    form = MaterialMovementQueryForm(request.query_params)

    if not form.is_valid():
        raise ValidationError(form.errors)

    dominio, sincronizacion = form.as_query()
    movimientos = material_movements(**dominio)

    movimientos = movimientos.select_related(
        "work_order__branch",
        "work_order__liquidation",
    )

    if sincronizacion["technician"] is not None:
        movimientos = movimientos.filter(
            work_order__assigned_technician_id=sincronizacion["technician"]
        )

    # Marca de agua real del contrato que se serializa.
    #
    # No basta con movement.updated_at + WorkOrder.updated_at. El feed también
    # expone el estado de revisión de la liquidación, y ese documento puede
    # pasar por envío, corrección, reenvío y validación sin modificar la OT ni
    # el movimiento. Las fechas propias de ese ciclo se incluyen explícitamente
    # para que un incremental vuelva a entregar la fila cuando cambie cualquiera
    # de los datos que logística observa.
    #
    # Coalesce evita la semántica distinta de Greatest con NULL entre SQLite y
    # PostgreSQL: si no existe liquidación, se usa el updated_at de la OT como
    # valor neutro y changed_at nunca queda en NULL por ese motivo.
    movimientos = movimientos.annotate(
        changed_at=Greatest(
            F("updated_at"),
            F("work_order__updated_at"),
            Coalesce(
                F("work_order__liquidation__updated_at"),
                F("work_order__updated_at"),
            ),
            Coalesce(
                F("work_order__liquidation__liquidated_at"),
                F("work_order__updated_at"),
            ),
            Coalesce(
                F("work_order__liquidation__submitted_at"),
                F("work_order__updated_at"),
            ),
            Coalesce(
                F("work_order__liquidation__correction_requested_at"),
                F("work_order__updated_at"),
            ),
            Coalesce(
                F("work_order__liquidation__resubmitted_at"),
                F("work_order__updated_at"),
            ),
            Coalesce(
                F("work_order__liquidation__validated_at"),
                F("work_order__updated_at"),
            ),
            output_field=DateTimeField(),
        )
    )

    if sincronizacion["updated_since"] is not None:
        movimientos = movimientos.filter(
            changed_at__gt=sincronizacion["updated_since"]
        )

    return movimientos


class LogisticsFeedPermissionMixin:
    """Autenticación por token y permiso de consulta de movimientos."""

    permission_classes = [IsAuthenticated, CanReadMaterialMovements]


class MaterialMovementListView(LogisticsFeedPermissionMixin, ListAPIView):
    """GET — movimientos del periodo, una fila por movimiento."""

    serializer_class = MaterialMovementSerializer
    pagination_class = MaterialMovementPagination

    def get_queryset(self):
        return _consultar(self.request)


class MaterialMovementIdListView(LogisticsFeedPermissionMixin, APIView):
    """GET — conjunto completo de ids que siguen vigentes en el periodo."""

    def get(self, request, *args, **kwargs):
        # Una reconciliación de borrados necesita el universo completo. Si se
        # aceptara updated_since, los ids no modificados quedarían fuera y el
        # consumidor podría borrarlos creyendo que ya no existen en SICV.
        if request.query_params.get("updated_since"):
            raise ValidationError({
                "updated_since": [
                    "No se admite en la reconciliación de ids; consulte el periodo completo."
                ]
            })

        movimientos = _consultar(request)
        total = movimientos.count()

        if total > MAX_RECONCILIATION_IDS:
            raise ValidationError({
                "detail": (
                    f"El periodo tiene {total} movimientos y el máximo para "
                    f"reconciliar de una vez es {MAX_RECONCILIATION_IDS}. "
                    "Pida el periodo en tramos más cortos."
                )
            })

        return Response({
            "count": total,
            "ids": list(movimientos.order_by("pk").values_list("pk", flat=True)),
        })


class MaterialMovementWatermarkView(LogisticsFeedPermissionMixin, APIView):
    """GET — el `changed_at` más alto del periodo."""

    def get(self, request, *args, **kwargs):
        movimientos = _consultar(request)

        return Response({
            "count": movimientos.count(),
            "watermark": movimientos.aggregate(ultimo=Max("changed_at"))["ultimo"],
        })
