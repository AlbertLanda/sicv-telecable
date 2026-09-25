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

from apps.organization.context_processors import get_active_branch

from .exporters import CONTENT_TYPES, render
from .forms import VIEWED_FORMATS, MaterialReportForm, SalesReportForm
from .materials import build_report
from .sales import build_sales_report


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

