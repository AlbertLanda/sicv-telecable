"""Los parámetros de consulta del feed, validados antes de tocar la base.

Es un `forms.Form` y no un serializador de entrada a propósito: la pantalla
web del reporte ya valida su periodo con `MaterialReportForm`, y las dos
consultas comparten reglas —las fechas son obligatorias, no pueden venir al
revés—. Resolverlas con la misma herramienta deja que se lean una al lado de
la otra; con un serializador habría que comparar dos mecanismos distintos para
saber si dicen lo mismo.

Lo que aquí se rechaza sale como `400` con el detalle por campo, que es lo que
permite que el otro sistema registre *qué* parámetro estaba mal en vez de
apuntar «falló la sincronización» en su log.
"""

from django import forms

from apps.organization.models import Branch
from apps.reports.materials import (
    DATE_BASIS_CHOICES,
    DEFAULT_SCOPE,
    SCOPE_CHOICES,
)


# La base de fecha por defecto del canal de logística **no** es la del reporte
# en pantalla.
#
# Quien consume este feed cuadra mochilas, y para eso la fecha que importa es
# la de atención: es cuando el material salió de la mochila. Que el defecto
# sea ese evita el error silencioso de sincronizar un mes entero por emisión y
# descubrir la diferencia recién al cuadrar, cuando ya nadie recuerda qué
# parámetro se usó.
DEFAULT_API_DATE_BASIS = "attended"


# Techo del periodo que se puede pedir de una vez.
#
# No es un límite de rendimiento —para eso está la paginación— sino un freno a
# la consulta absurda: un `date_from` con el año mal tecleado pide dos décadas
# y mantiene ocupado al servidor construyendo un recuento que nadie pidió. Un
# año cubre de sobra la carga inicial y cualquier reconciliación.
MAX_RANGE_DAYS = 366


class MaterialMovementQueryForm(forms.Form):
    """Periodo, recorte y base de fecha del feed de movimientos."""

    date_from = forms.DateField()
    date_to = forms.DateField()

    date_basis = forms.ChoiceField(
        choices=DATE_BASIS_CHOICES,
        required=False,
    )

    scope = forms.ChoiceField(
        choices=SCOPE_CHOICES,
        required=False,
    )

    # La sede viaja por **código** y no por id. El código es el que logística
    # ya conoce —es el que aparece impreso en la cabecera del reporte— y no
    # cambia al recrear la fila; el id es un detalle de esta base de datos que
    # el otro sistema no tiene por qué aprender.
    branch = forms.CharField(required=False)

    technician = forms.IntegerField(required=False)

    updated_since = forms.DateTimeField(required=False)

    def clean_branch(self):
        """Resuelve el código de sede, o explica que no existe.

        Un código desconocido es un `400` y no una lista vacía: vacío se lee
        como «esta sede no movió material esta semana», que es justo la
        conclusión equivocada cuando lo que pasó es que el código venía mal
        escrito.
        """
        codigo = (self.cleaned_data.get("branch") or "").strip()

        if not codigo:
            return None

        try:
            return Branch.objects.get(code=codigo)
        except Branch.DoesNotExist:
            raise forms.ValidationError(f"No existe la sede «{codigo}».")

    def clean_date_basis(self):
        return self.cleaned_data.get("date_basis") or DEFAULT_API_DATE_BASIS

    def clean_scope(self):
        return self.cleaned_data.get("scope") or DEFAULT_SCOPE

    def clean(self):
        cleaned = super().clean()

        desde = cleaned.get("date_from")
        hasta = cleaned.get("date_to")

        if desde and hasta:
            # Mismo criterio que la pantalla: un periodo al revés se rechaza
            # en vez de devolver vacío, porque vacío es una respuesta legítima
            # a una consulta bien hecha y no se distingue del error.
            if desde > hasta:
                raise forms.ValidationError(
                    "La fecha inicial no puede ser posterior a la final."
                )

            if (hasta - desde).days > MAX_RANGE_DAYS:
                raise forms.ValidationError(
                    f"El periodo no puede superar {MAX_RANGE_DAYS} días."
                )

        return cleaned

    def as_query(self):
        """Los parámetros listos para `material_movements()` y sus extras.

        Devuelve dos diccionarios separados porque no van al mismo sitio: el
        primero es la consulta del dominio, compartida con el reporte en
        pantalla, y el segundo son los recortes propios de la sincronización,
        que se aplican encima. Mezclarlos empujaría a `materials.py` detalles
        que solo existen porque hay otro sistema al otro lado.
        """
        dominio = {
            "branch": self.cleaned_data["branch"],
            "date_from": self.cleaned_data["date_from"],
            "date_to": self.cleaned_data["date_to"],
            "scope": self.cleaned_data["scope"],
            "date_basis": self.cleaned_data["date_basis"],
        }

        sincronizacion = {
            "technician": self.cleaned_data["technician"],
            "updated_since": self.cleaned_data["updated_since"],
        }

        return dominio, sincronizacion

