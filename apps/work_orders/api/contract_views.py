"""La contrata del abonado dentro de la orden de instalación.

El contrato se firma donde está el abonado, y el abonado está en su casa el
día de la instalación. Por eso el canal del técnico entrega el mismo contrato
que SICV imprime y recoge encima la firma: no es un documento nuevo del
portal, es el documento de siempre visto desde el sitio donde hay alguien que
puede firmarlo.

Este módulo es **canal, no dominio**. Resuelve de qué contrato habla la orden
y quién puede tocarlo ahora; qué es una firma y cómo se guarda lo decide
`apps.contracts.signatures`, y cómo se dibuja el contrato, `apps.contracts.pdf`.

Va por token como el resto del canal: el técnico no tiene sesión web, así que
la pantalla de contratos de SICV -que sí la exige- no le sirve. Es la misma
razón por la que la ficha técnica y las evidencias tienen aquí su endpoint y
no reutilizan las vistas web.
"""

import json
from io import BytesIO

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.contracts.pdf import render_contract
from apps.contracts.signatures import (
    borrar_firma,
    contrato_de_la_orden,
    firma_del_contrato,
    firmar_contrato,
    mover_firma,
)
from apps.work_orders.api.field_serializers import (
    ContractSignaturePlacementSerializer,
    ContractSignatureUploadSerializer,
)
from apps.work_orders.api.views import TechnicianWorkOrderObjectMixin
from apps.work_orders.models import WorkOrder
from apps.work_orders.services import INSTALLATION_ORDER_TYPE_CODE


SIN_CONTRATO = (
    "Esta orden no tiene una contrata que firmar."
)

NO_ES_INSTALACION = (
    "La contrata se firma en la instalación del servicio."
)

NO_ESTA_EN_ATENCION = (
    "La contrata solo puede firmarse mientras la orden está En atención."
)

# Cabecera donde el PDF lleva su propio hueco de firma. Es de este canal, no
# del dominio: describe cómo se sirve el archivo, igual que su nombre.
CABECERA_DEL_ANCLA = "X-Contrata-Ancla"


class ContractOfOrderMixin(TechnicianWorkOrderObjectMixin):
    """Resuelve la orden y su contrata, con las reglas de quién puede firmar.

    Las dos condiciones -que la orden sea de instalación y que esté en
    atención- se comprueban aquí y no en cada vista: la lectura las publica
    para que el portal sepa qué botón pintar, y la escritura las exige. Si
    vivieran por separado, el portal podría ofrecer una firma que el servidor
    rechaza.
    """

    def get_contract(self):
        """La contrata de la orden, o `None` si esta orden no tiene ninguna."""

        if not hasattr(self, "_contract"):
            order = self.get_object()

            self._order = order
            self._contract = (
                contrato_de_la_orden(order)
                if order.order_type.code == INSTALLATION_ORDER_TYPE_CODE
                else None
            )

        return self._contract

    def motivo_para_no_firmar(self, order, contract):
        """Por qué no se puede firmar ahora, o `None` si sí se puede."""

        if order.order_type.code != INSTALLATION_ORDER_TYPE_CODE:
            return NO_ES_INSTALACION

        if contract is None:
            return SIN_CONTRATO

        if order.status != WorkOrder.Status.IN_PROGRESS:
            return NO_ESTA_EN_ATENCION

        return None

    def estado_de_la_contrata(self, order, contract):
        """Lo que el portal necesita para pintar el apartado Contrata."""

        motivo = self.motivo_para_no_firmar(order, contract)

        if contract is None:
            return {
                "available": False,
                "contract": None,
                "signature": None,
                "can_sign": False,
                "detail": motivo,
            }

        firma = firma_del_contrato(contract)

        return {
            "available": True,
            "contract": {
                "id": contract.pk,
                "number": contract.contract_number,
                "customer": str(contract.customer),
                "document_type": contract.customer.get_document_type_display(),
                "document_number": contract.customer.document_number,
                "service": f"{contract.service_type} – {contract.plan}",
                "start_date": contract.start_date,
            },
            "signature": (
                {
                    "signer_name": firma.signer_name,
                    "signed_at": firma.signed_at,
                    "placement": firma.colocacion,
                    "captured_by": (
                        firma.captured_by.get_full_name()
                        or firma.captured_by.username
                    )
                    if firma.captured_by
                    else None,
                }
                if firma
                else None
            ),
            "can_sign": motivo is None,
            "detail": motivo,
        }


class WorkOrderContractView(ContractOfOrderMixin, GenericAPIView):
    """GET — el estado de la contrata de esta orden.

    Responde 200 aunque la orden no tenga contrata: que una avería no traiga
    contrato no es un error del técnico, es lo normal. El portal lee
    `available` y decide si pinta el apartado.
    """

    serializer_class = None

    def get(self, request, *args, **kwargs):
        contract = self.get_contract()

        return Response(self.estado_de_la_contrata(self._order, contract))


class WorkOrderContractDocumentView(ContractOfOrderMixin, GenericAPIView):
    """GET — el contrato en PDF, el mismo que imprime SICV.

    Llega *inline* y siempre completo: con la firma dentro si el abonado ya
    firmó, y con la línea en blanco si todavía no. No hay dos documentos, hay
    uno que se dibuja con lo que hay registrado en ese momento.

    Se entrega aunque la orden ya esté cerrada: el técnico tiene que poder
    volver a mirar lo que se firmó en un domicilio al que ya no va a volver.
    """

    serializer_class = None

    def get(self, request, *args, **kwargs):
        contract = self.get_contract()

        if contract is None:
            return Response(
                {"detail": SIN_CONTRATO},
                status=status.HTTP_404_NOT_FOUND,
            )

        buffer = BytesIO()
        ancla = {}
        nombre = render_contract(
            contract,
            buffer,
            ancla=ancla,
            # `?sin_firma=1` devuelve la hoja como estaba antes de firmarla.
            # Es lo que se mira mientras se arrastra el trazo: con la firma
            # dibujada debajo se verían dos.
            con_firma=request.GET.get("sin_firma") != "1",
        )
        buffer.seek(0)

        respuesta = FileResponse(
            buffer,
            as_attachment=False,
            filename=nombre,
            content_type="application/pdf",
        )

        # Dónde quedó el hueco de firma en este documento: página y medidas,
        # en las unidades del PDF. Viaja con el propio archivo -y no en una
        # llamada aparte- porque describe a este PDF y no al contrato: pedir
        # las dos cosas por separado abriría la puerta a que el visor
        # colocara la firma según un documento que ya no es el que muestra.
        respuesta[CABECERA_DEL_ANCLA] = json.dumps(ancla)

        return respuesta


class WorkOrderContractSignatureView(ContractOfOrderMixin, GenericAPIView):
    """POST — el abonado acepta su firma. DELETE — la rechaza.

    Rehacer es reemplazar, y solo mientras la orden sigue en atención: al
    cerrarla queda la firma que el abonado aceptó. Ese límite es el mismo que
    ya gobierna la ficha técnica y las evidencias, así que el técnico no tiene
    que aprender una regla nueva por pantalla.
    """

    serializer_class = ContractSignatureUploadSerializer
    # El trazo llega como archivo; moverlo, como JSON. Recolocar una firma no
    # sube nada, así que obligar a multipart solo para decir tres números
    # sería pedirle al cliente que empaquete un formulario sin campos.
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _contrata_firmable(self):
        """Devuelve (contrato, respuesta de error). Solo una de las dos."""

        contract = self.get_contract()
        motivo = self.motivo_para_no_firmar(self._order, contract)

        if contract is None:
            return None, Response(
                {"detail": motivo},
                status=status.HTTP_404_NOT_FOUND,
            )

        if motivo is not None:
            return None, Response(
                {"detail": motivo},
                status=status.HTTP_409_CONFLICT,
            )

        return contract, None

    def get(self, request, *args, **kwargs):
        """El trazo guardado, tal cual se dibujó.

        Lo pide el visor para volver a ponerlo en pantalla cuando el técnico
        toca la firma del documento: lo que se mueve es el mismo dibujo, no
        una copia repintada.
        """

        contract = self.get_contract()
        firma = firma_del_contrato(contract) if contract else None

        if firma is None or not firma.image:
            return Response(
                {"detail": "Este contrato todavía no está firmado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return FileResponse(
            firma.image.open("rb"),
            as_attachment=False,
            filename="firma.png",
            content_type="image/png",
        )

    def patch(self, request, *args, **kwargs):
        """Mueve o cambia de tamaño la firma que ya está registrada.

        No recibe imagen: el trazo es el mismo y el abonado no tiene que
        volver a firmar porque su firma quedara torcida en la hoja.
        """

        contract, error = self._contrata_firmable()
        if error is not None:
            return error

        serializer = ContractSignaturePlacementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        datos = serializer.validated_data

        try:
            mover_firma(
                contract,
                {
                    "x": datos.get("offset_x"),
                    "y": datos.get("offset_y"),
                    "ancho": datos.get("width"),
                },
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": " ".join(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(self.estado_de_la_contrata(self._order, contract))

    def post(self, request, *args, **kwargs):
        contract, error = self._contrata_firmable()
        if error is not None:
            return error

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        datos = serializer.validated_data

        try:
            firmar_contrato(
                contract,
                datos["image"],
                usuario=request.user,
                orden=self._order,
                colocacion={
                    "x": datos.get("offset_x"),
                    "y": datos.get("offset_y"),
                    "ancho": datos.get("width"),
                },
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": " ".join(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            self.estado_de_la_contrata(self._order, contract),
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, *args, **kwargs):
        contract, error = self._contrata_firmable()
        if error is not None:
            return error

        borrar_firma(contract)

        return Response(self.estado_de_la_contrata(self._order, contract))
