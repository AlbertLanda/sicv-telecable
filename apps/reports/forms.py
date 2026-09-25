"""El formulario del reporte: periodo, alcance y formato."""

from django import forms
from django.utils import timezone
from django.db.models import Q

from apps.accounts.models import User

from .materials import DEFAULT_SCOPE, SCOPE_CHOICES


# Los cuatro formatos del sistema anterior, en su mismo orden.
FORMAT_CHOICES = [
    ("PDF", "PDF"),
    ("WORD", "Word"),
    ("EXCEL", "Excel"),
    ("HTML", "Html"),
]

DEFAULT_FORMAT = "HTML"


# Los formatos que el navegador **pinta** en vez de descargar. Son los que
# abren pestaña: si salieran sobre la pantalla actual, la hoja taparía el
# formulario y volver a consultar obligaría a retroceder.
#
# El PDF entra aquí porque se sirve `inline` y el navegador lo abre en su
# propio visor. Word y Excel no los sabe pintar ninguno, así que los descarga:
# abrirles una pestaña dejaría una en blanco detrás de la descarga que el
# operador tiene que cerrar a mano en cada reporte.
#
# La lista vive aquí y no escrita a mano en el JavaScript de la plantilla para
# que sea comprobable: una prueba la lee y verifica que la pantalla ofrece
# exactamente estos.
VIEWED_FORMATS = ("HTML", "PDF")


class MaterialReportForm(forms.Form):
    """Periodo, alcance y formato del reporte de materiales.

    Abre con el día de hoy en las dos fechas -como el sistema que se
    reemplaza-, de modo que «Imprimir» sin tocar nada responde por la jornada
    en curso, que es la consulta que más se hace en ventanilla.
    """

    date_from = forms.DateField(
        label="Desde",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"},
            format="%Y-%m-%d",
        ),
    )

    date_to = forms.DateField(
        label="Hasta",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"},
            format="%Y-%m-%d",
        ),
    )

    scope = forms.ChoiceField(
        label="Reporte",
        choices=SCOPE_CHOICES,
        initial=DEFAULT_SCOPE,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    export_format = forms.ChoiceField(
        label="Formato",
        choices=FORMAT_CHOICES,
        initial=DEFAULT_FORMAT,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        hoy = timezone.localdate()
        self.fields["date_from"].initial = hoy
        self.fields["date_to"].initial = hoy

    def clean(self):
        cleaned = super().clean()

        desde = cleaned.get("date_from")
        hasta = cleaned.get("date_to")

        # Se valida aquí y no en cada campo porque la regla habla de los dos a
        # la vez. Invertido, el reporte no fallaría: saldría vacío, y un
        # reporte vacío se lee como «no hubo movimientos», que es una
        # respuesta distinta de «el periodo está al revés».
        if desde and hasta and desde > hasta:
            raise forms.ValidationError(
                "La fecha inicial no puede ser posterior a la final."
            )

        return cleaned

class SalesReportForm(forms.Form):
    """Día y vendedor opcional para el control comercial."""

    day = forms.DateField(
        label="Fecha",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"},
            format="%Y-%m-%d",
        ),
    )
    seller = forms.ModelChoiceField(
        label="Vendedor",
        queryset=User.objects.none(),
        required=False,
        empty_label="Todos los vendedores",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["day"].initial = timezone.localdate()
        self.fields["seller"].queryset = (
            User.objects
            .filter(
                Q(is_salesperson=True)
                | Q(role=User.Role.SALES)
                | Q(role=User.Role.ADMIN)
                | Q(sold_subscriptions__isnull=False)
            )
            .distinct()
            .order_by("first_name", "last_name", "username")
        )

