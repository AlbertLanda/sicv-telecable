"""El reporte de materiales: la pantalla que lo pide y la hoja que sale.

Son dos vistas y dos URL a propósito:

    /reportes/materiales/          el formulario
    /reportes/materiales/listar/   la hoja ya resuelta

La hoja se abre en una pestaña nueva, como en el sistema que se reemplaza, y
por eso necesita una URL propia que se pueda pegar, recargar y guardar en
favoritos. Con el resultado incrustado bajo el formulario esa URL no existía:
recargar reenviaba el formulario y compartir el reporte obligaba a explicar
por escrito qué fechas había que escribir para reproducirlo.

Los parámetros viajan por GET por la misma razón. Un POST en una pestaña nueva
convierte cada recarga en un aviso de reenvío del navegador, que es justo lo
que el operador hace cuando quiere el mismo reporte un rato después.
"""

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import FileResponse
from django.template.response import TemplateResponse
from django.views.generic import FormView, TemplateView

from apps.organization.context_processors import get_active_branch, get_active_office

from . import cash_closing_exporters, user_income_exporters
from .cash_closing import USER_REPORT_TYPE, build_cash_closing
from .exporters import CONTENT_TYPES, render
from .forms import (
    VIEWED_FORMATS,
    CashClosingForm,
    MaterialReportForm,
    SalesReportForm,
    cash_closing_defaults,
)
from .materials import build_report
from .sales import build_sales_report
from .user_income import build_user_income


class MaterialReportPermissionMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Quién puede sacar el reporte.

    El permiso es el de consultar movimientos de material, no uno propio del
    reporte: quien puede ver un movimiento en la ficha de una orden puede
    verlo también sumado en una lista, y crear un segundo permiso para el
    mismo dato solo daría dos respuestas distintas a la misma pregunta.

    Vive en un mixin porque lo comparten el formulario y la hoja: declarado en
    cada una, bastaría con olvidarlo en la segunda para que la hoja quedara
    abierta a cualquiera con sesión iniciada.
    """

    permission_required = "inventory.view_workordermaterialmovement"


class MaterialReportView(MaterialReportPermissionMixin, FormView):
    """Periodo, alcance y formato. No consulta nada: solo pide los datos."""

    template_name = "reports/material_report.html"
    form_class = MaterialReportForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["branch"] = get_active_branch(self.request)
        context["viewed_formats"] = VIEWED_FORMATS

        return context


class MaterialReportListView(MaterialReportPermissionMixin, TemplateView):
    """La hoja: en pantalla si se pidió Html, como archivo en los otros tres.

    Un formulario inválido -un periodo al revés, una fecha en blanco- vuelve a
    la pantalla anterior con su mensaje en vez de pintar una hoja vacía. Una
    hoja sin filas se lee como «no hubo movimientos», que es una respuesta
    distinta de «la consulta estaba mal escrita».
    """

    template_name = "reports/material_report_sheet.html"

    def get(self, request, *args, **kwargs):
        form = MaterialReportForm(request.GET)

        if not form.is_valid():
            # Se devuelve el formulario **ligado**, con lo que el operador
            # escribió y el error encima. Reenviarlo a la vista del formulario
            # lo pintaría vacío: el mensaje se perdería y la pantalla parecería
            # no haber hecho nada.
            return TemplateResponse(
                request,
                MaterialReportView.template_name,
                {
                    "form": form,
                    "branch": get_active_branch(request),
                    "viewed_formats": VIEWED_FORMATS,
                },
            )

        report = build_report(
            branch=get_active_branch(request),
            date_from=form.cleaned_data["date_from"],
            date_to=form.cleaned_data["date_to"],
            scope=form.cleaned_data["scope"],
        )

        export_format = form.cleaned_data["export_format"]

        if export_format == "HTML":
            return self.render_to_response({"report": report})

        buffer, nombre = render(report, export_format)

        # `inline` y no `attachment`: el PDF se abre en el visor del navegador,
        # que ya trae sus botones de imprimir y guardar. Excel y Word no los
        # sabe pintar ninguno, así que esos los descarga igual por su cuenta.
        return FileResponse(
            buffer,
            as_attachment=False,
            filename=nombre,
            content_type=CONTENT_TYPES[export_format],
        )

class SalesReportView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """Ventas del día agrupadas por vendedor y su detalle de auditoría."""

    template_name = "reports/sales_report.html"
    permission_required = "services.view_subscription"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        branch = get_active_branch(self.request)

        data = self.request.GET.copy()
        if not data:
            from django.utils import timezone
            data = {"day": timezone.localdate().isoformat()}

        form = SalesReportForm(data)

        context["form"] = form
        context["branch"] = branch
        context["report"] = None

        if form.is_valid():
            context["report"] = build_sales_report(
                day=form.cleaned_data["day"],
                branch=branch,
                seller=form.cleaned_data.get("seller"),
            )

        return context


class CashClosingPermissionMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Quién puede sacar el cierre de caja: Contabilidad.

    Es un permiso propio y no el de consultar comprobantes, que ATC ya tiene
    para atender en la ficha: el cierre suma la recaudación de toda la sede.
    """

    permission_required = "payments.view_cash_closing"


class CashClosingView(CashClosingPermissionMixin, TemplateView):
    """Reportes › Cierre de caja: el formulario, y el consolidado como archivo.

    Misma pantalla que el reporte de materiales: campos, «Formato» y
    «Exportar». El consolidado de emisión y los ingresos por usuario salen en
    Excel o PDF, que es donde Contabilidad los trabaja.

    El formulario viaja por GET a esta misma dirección. Llega enviado cuando
    trae su «Formato»; sin él es la primera visita, y el formulario abre con
    el mes en curso. Un envío inválido vuelve aquí con el formulario ligado,
    para que el mensaje aparezca sobre lo que el operador escribió.

    La sede es siempre la activa. Sin «Consolidado oficinas», además, solo la
    oficina activa de la barra superior: es la que el operador tiene a la
    vista, y pedirla otra vez en el formulario daría dos respuestas a la
    misma pregunta.
    """

    template_name = "reports/cash_closing.html"

    def get(self, request, *args, **kwargs):
        branch = get_active_branch(request)
        submitted = "export_format" in request.GET

        if submitted:
            form = CashClosingForm(request.GET, branch=branch)
        else:
            form = CashClosingForm(initial=cash_closing_defaults(), branch=branch)

        if submitted and form.is_valid():
            office = None

            if branch is None:
                form.add_error(
                    None,
                    "No hay una sede activa. Elige una en la barra superior.",
                )

            elif not form.cleaned_data["all_offices"]:
                office = get_active_office(request, branch=branch)

                if office is None:
                    form.add_error(
                        "all_offices",
                        "No hay una oficina activa. Elige una en la barra "
                        "superior o marca «Consolidado oficinas».",
                    )

            if not form.errors:
                filters = {
                    "branch": branch,
                    "date_from": form.cleaned_data["date_from"],
                    "date_to": form.cleaned_data["date_to"],
                    "office": office,
                    "issuer": form.cleaned_data["issuer"],
                    "sequence": form.cleaned_data["sequence"],
                    "user": form.cleaned_data["user"],
                }
                report_type = form.cleaned_data["report_type"]
                export_format = form.cleaned_data["export_format"]

                # «Ingresos por usuario» no es la hoja del consolidado
                # recortada: es otra hoja, una fila por concepto cobrado.
                if report_type == USER_REPORT_TYPE:
                    report = build_user_income(**filters)
                    buffer, nombre = user_income_exporters.render(
                        report, export_format
                    )
                else:
                    report = build_cash_closing(
                        **filters,
                        report_type=report_type,
                        printed_by=request.user.username,
                    )
                    buffer, nombre = cash_closing_exporters.render(
                        report, export_format
                    )

                # `inline`, como en materiales: el PDF se abre en el visor del
                # navegador y el Excel se descarga igual por su cuenta.
                return FileResponse(
                    buffer,
                    as_attachment=False,
                    filename=nombre,
                    content_type=cash_closing_exporters.CONTENT_TYPES[export_format],
                )

        return self.render_to_response(
            self.get_context_data(
                form=form,
                branch=branch,
                viewed_formats=VIEWED_FORMATS,
                user_report_type=USER_REPORT_TYPE,
            )
        )
