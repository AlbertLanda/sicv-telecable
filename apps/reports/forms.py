"""El formulario del reporte: periodo, alcance y formato."""

from django import forms
from django.utils import timezone
from django.db.models import Q

from apps.accounts.models import User
from apps.payments.models import Issuer, ReceiptSequence

from .cash_closing import (
    DEFAULT_REPORT_TYPE,
    REPORT_TYPE_CHOICES,
    USER_REPORT_TYPE,
)
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



# El cierre de caja sale en Excel -el formato con el que trabaja
# Contabilidad- o en PDF para firmarlo y archivarlo.
CASH_CLOSING_FORMAT_CHOICES = [
    ("EXCEL", "Excel"),
    ("PDF", "PDF"),
]

DEFAULT_CASH_CLOSING_FORMAT = "EXCEL"


class CashClosingForm(forms.Form):
    """Los campos de Reportes › Cierre de caja, los mismos de SICAV y en su
    orden.

    «Consolidado oficinas» marcado es la sede entera. Desmarcado, el cierre
    se limita a la oficina activa de la barra superior.

    «Empresa» abre en «Todas»: sin elegir una, el cierre suma todas las
    empresas de la sede, que es como se cuadra la caja.

    «Usuario» solo cuenta en «Ingresos por usuario»: vacío salen todos los que
    cobraron, como con el «NINGUNO» de SICAV. En los demás reportes queda
    bloqueado y lo que traiga se descarta: un usuario elegido que no se ve
    aplicado haría pasar por consolidado el cierre de un solo cajero.
    """

    issuer = forms.ModelChoiceField(
        label="Empresa",
        queryset=Issuer.objects.all(),
        required=False,
        empty_label="Todas",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

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

    report_type = forms.ChoiceField(
        label="Reporte",
        choices=REPORT_TYPE_CHOICES,
        initial=DEFAULT_REPORT_TYPE,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    user = forms.ModelChoiceField(
        label="Usuario",
        queryset=User.objects.none(),
        required=False,
        empty_label="Todos",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    sequence = forms.ModelChoiceField(
        label="Serie",
        queryset=ReceiptSequence.objects.select_related("issuer"),
        required=False,
        empty_label="Todas",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    export_format = forms.ChoiceField(
        label="Formato",
        choices=CASH_CLOSING_FORMAT_CHOICES,
        initial=DEFAULT_CASH_CLOSING_FORMAT,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    all_offices = forms.BooleanField(
        label="Consolidado oficinas",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, branch=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Solo quienes registraron cobros en la sede: una lista con todo el
        # personal obligaría a buscar entre técnicos y NOC que nunca cobran.
        usuarios = User.objects.filter(payments_received__isnull=False)

        if branch is not None:
            usuarios = usuarios.filter(payments_received__branch=branch)

        self.fields["user"].queryset = usuarios.distinct().order_by(
            "first_name", "last_name", "username"
        )

        # Bloqueado en el servidor y no solo en el navegador: un campo
        # deshabilitado se pinta con `disabled` y Django ignora lo que llegue
        # por él, aunque alguien lo escriba a mano en la dirección.
        if self.is_bound:
            report_type = self.data.get(self.add_prefix("report_type"))
        else:
            report_type = self.initial.get("report_type", DEFAULT_REPORT_TYPE)

        self.fields["user"].disabled = report_type != USER_REPORT_TYPE

    def clean(self):
        cleaned = super().clean()

        desde = cleaned.get("date_from")
        hasta = cleaned.get("date_to")

        if desde and hasta and desde > hasta:
            raise forms.ValidationError(
                "La fecha inicial no puede ser posterior a la final."
            )

        return cleaned


def cash_closing_defaults():
    """Con qué abre el cierre de caja: el mes en curso hasta hoy, la sede
    entera y todas sus empresas. Es el cuadre que Contabilidad pide más a
    menudo, así que la pantalla ya llega respondiéndolo.

    Son valores iniciales y no un envío: la primera visita no se valida, y
    ningún aviso aparece antes de que el operador haya tocado nada."""
    hoy = timezone.localdate()

    return {
        "date_from": hoy.replace(day=1),
        "date_to": hoy,
        "report_type": DEFAULT_REPORT_TYPE,
        "export_format": DEFAULT_CASH_CLOSING_FORMAT,
        "all_offices": True,
    }
