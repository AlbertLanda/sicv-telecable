"""El contrato de abonado como PDF, para verlo o para llevárselo.

Es el documento que el abonado firma: las cláusulas completas, con los datos
que el SICV ya tiene -cliente, domicilio de instalación, servicio, plan,
velocidad, tarifas y fechas- puestos en los espacios que antes se llenaban a
mano.

Sale como archivo y no como pantalla por la misma razón que el comprobante de
cobranza: lo que pasa por la impresora tiene que ser el papel. El botón lo
abre en la pestaña de al lado, en el visor del navegador, que ya trae sus
propios botones de imprimir y guardar; no hay una página intermedia que
duplique el documento ni un diálogo que salte sin que nadie lo pida.

Vive en su propio módulo, como la impresión de la orden de trabajo: el papel
tiene reglas propias -medidas, márgenes, dónde parte una hoja- que no son las
de una pantalla.
"""

from io import BytesIO

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse
from django.views.generic.detail import SingleObjectMixin
from django.views.generic import View

from .models import Contract
from .pdf import render_contract
from .signatures import firma_del_contrato


class ContractDocumentPdfView(LoginRequiredMixin, SingleObjectMixin, View):
    """Un mismo contrato, en el formato y el destino que se pidan.

    - `?ver=1` llega *inline*: el navegador lo pinta en su visor, en la
      pestaña de al lado. Es lo que hace el botón «Imprimir contrato».
    - Sin `ver` llega como `attachment`: se guarda en el disco.

    El alcance es el mismo que el del resumen del contrato: el contrato tiene
    que pertenecer al cliente de la URL, así que un enlace con el cliente
    cambiado no entrega el contrato de otro.
    """

    model = Contract

    def get_queryset(self):
        return (
            Contract.objects
            .filter(customer_id=self.kwargs["customer_pk"])
            .select_related(
                "customer",
                "customer__branch",
                "service_type",
                "plan",
                "subscription",
                "subscription__address",
            )
        )

    def get(self, request, *args, **kwargs):
        contract = self.get_object()

        firma = firma_del_contrato(contract)

        if firma is not None and firma.signed_pdf:
            return FileResponse(
                firma.signed_pdf.open("rb"),
                as_attachment=request.GET.get("ver") != "1",
                filename=f"{contract.contract_number}.pdf",
                content_type="application/pdf",
            )

        buffer = BytesIO()
        nombre = render_contract(contract, buffer)
        buffer.seek(0)

        return FileResponse(
            buffer,
            as_attachment=request.GET.get("ver") != "1",
            filename=nombre,
            content_type="application/pdf",
        )
