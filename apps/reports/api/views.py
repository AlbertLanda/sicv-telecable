"""El feed de movimientos de material para el sistema de logística.

Dos endpoints y dos preguntas distintas:

    GET /api/logistics/material-movements/        el detalle del periodo
    GET /api/logistics/material-movements/ids/    qué sigue existiendo

El primero entrega **el detalle, no el agregado**. Logística tabula por
técnico del otro lado -es lo que hoy hace a mano con una tabla dinámica sobre
el Excel- y ese total tiene que poder abrirse: cuando el cuadre de mochila no
cierra por unos metros de fibra, alguien tiene que llegar a las órdenes que
componen la suma. Un endpoint que devolviera el total ya sumado convertiría
esa pregunta en una llamada telefónica.

El segundo existe por los borrados. Un técnico puede retirar un material que
declaró por error (`inventory.services.delete_work_order_material`), y una
sincronización que solo trae altas y cambios no se entera nunca: la fila
sobrevive en logística descontando stock que volvió al almacén. Devolviendo
los ids vigentes de un periodo, el otro sistema borra lo que le sobra. Se
resuelve así, y no con un borrado lógico, para no tocar el dominio de
inventario por una necesidad que es de la integración.

Ninguno de los dos consulta la base por su cuenta: los dos parten de
`materials.material_movements()`, el mismo queryset que imprime la hoja en
pantalla. Es lo que garantiza que el reporte y el cuadre den el mismo número —
con dos consultas paralelas, la primera diferencia aparecería en un
descuadre de almacén y nadie sabría cuál de las dos está mal.
"""

from django.db.models import DateTimeField, F, Max
from django.db.models.functions import Greatest
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


# Tope de ids que devuelve la reconciliación de una sola vez.
#
# No se pagina porque el consumidor necesita el conjunto **completo** para
# poder restar: con media lista borraría filas vigentes que simplemente no
# alcanzaron a entrar. Si un periodo supera el tope, la respuesta lo dice y
# pide partirlo, que es preferible a entregar una lista incompleta que el
# otro lado no puede distinguir de una completa.
MAX_RECONCILIATION_IDS = 100_000


def _consultar(request):
    """Valida los parámetros y arma el queryset del periodo pedido.

    Devuelve el queryset ya anotado con `changed_at`. Lo comparten los dos
    endpoints: si cada uno armara su consulta, la lista de ids podría dejar
    fuera movimientos que el detalle sí trae, y la reconciliación borraría en
    logística filas que aquí siguen vivas.
    """
    form = MaterialMovementQueryForm(request.query_params)

    if not form.is_valid():
        # `form.errors` ya viene por campo; DRF lo publica como `400` con esa
        # misma forma, que es lo que permite al otro sistema registrar qué
        # parámetro estaba mal en vez de «falló la sincronización».
        raise ValidationError(form.errors)

    dominio, sincronizacion = form.as_query()

    movimientos = material_movements(**dominio)

    # La liquidación y la sede se traen en la misma consulta. Sin esto, cada
    # fila serializada dispara dos consultas más, y quinientas filas por
    # página convierten una descarga en mil viajes a la base.
    movimientos = movimientos.select_related(
        "work_order__branch",
        "work_order__liquidation",
    )

    if sincronizacion["technician"] is not None:
        movimientos = movimientos.filter(
            work_order__assigned_technician_id=sincronizacion["technician"]
        )

    # La marca de agua de la sincronización: lo más reciente entre el cambio
    # del movimiento y el de su orden.
    #
    # Mirar solo el movimiento no alcanza. Liquidar, atender o cerrar una
    # orden no toca sus filas de material, así que un incremental que se
    # guiara por `movement.updated_at` entregaría una vez cada movimiento y
    # nunca más — y el `is_liquidated` de logística se quedaría en falso para
    # siempre, que es justo el campo con el que decide si consolida.
    movimientos = movimientos.annotate(
        changed_at=Greatest(
            F("updated_at"),
            F("work_order__updated_at"),
            output_field=DateTimeField(),
        )
    )

    if sincronizacion["updated_since"] is not None:
        movimientos = movimientos.filter(
            changed_at__gt=sincronizacion["updated_since"]
        )

    return movimientos


class LogisticsFeedPermissionMixin:
    """Autenticación por token y permiso de consulta de movimientos.

    `IsAuthenticated` responde «sé quién eres» y ya está puesto en los ajustes
    globales; se repite aquí porque declarar `permission_classes` los
    reemplaza por completo, y omitirlo dejaría el feed abierto a cualquiera
    con token — incluidos los de los técnicos.
    """

    permission_classes = [IsAuthenticated, CanReadMaterialMovements]


class MaterialMovementListView(LogisticsFeedPermissionMixin, ListAPIView):
    """GET — los movimientos de material del periodo, uno por fila.

    Una orden que instaló tres materiales y retiró uno son cuatro filas, igual
    que en la hoja. Es lo que permite que la columna «Cantidad» sume lo que
    realmente se movió.
    """

    serializer_class = MaterialMovementSerializer
    pagination_class = MaterialMovementPagination

    def get_queryset(self):
        return _consultar(self.request)


class MaterialMovementIdListView(LogisticsFeedPermissionMixin, APIView):
    """GET — los ids que siguen existiendo en el periodo.

    La respuesta es deliberadamente pobre: un recuento y una lista de enteros.
    No lleva el detalle porque no se usa para mostrar nada, sino para restar —
    lo que el otro sistema tiene guardado y aquí ya no aparece es lo que hay
    que borrar allá.
    """

    def get(self, request, *args, **kwargs):
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
    """GET — el `changed_at` más alto del periodo.

    Es la marca de agua que el otro sistema guarda para su siguiente
    incremental. Se pide **a este sistema** y no se calcula allá con su propio
    reloj: si los dos servidores difieren en unos segundos, una marca calculada
    localmente se salta movimientos en cada corrida, y el hueco no se nota
    hasta que el cuadre no cierra.

    Un periodo sin movimientos devuelve `null`, que el consumidor debe leer
    como «no muevas tu marca», no como «no hay nada más».
    """

    def get(self, request, *args, **kwargs):
        movimientos = _consultar(request)

        return Response({
            "count": movimientos.count(),
            "watermark": movimientos.aggregate(ultimo=Max("changed_at"))["ultimo"],
        })
