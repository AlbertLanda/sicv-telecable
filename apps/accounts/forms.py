from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from apps.accounts.models import User


class StyledPasswordChangeForm(PasswordChangeForm):
    """
    PasswordChangeForm estándar de Django, solo con clases de Bootstrap
    en los widgets. No cambia ninguna validación: la clave actual, la
    fuerza de la nueva y la coincidencia entre ambas las sigue
    verificando Django, no esta clase.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class ProfileContactForm(forms.ModelForm):
    """
    Edición del propio perfil, acotada a datos de contacto.

    Identidad (username, nombres, apellidos, rol, sede, oficina) no
    forma parte de este formulario a propósito: no es que se muestre
    de solo lectura en la plantilla, es que el campo no existe aquí,
    así que un POST manipulado con esas claves no tiene dónde
    aterrizar. Quien necesite corregir un dato de identidad lo hace
    desde el admin, no desde la propia cuenta.
    """

    class Meta:
        model = User
        fields = ["phone", "email"]
        widgets = {
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
        }
        labels = {
            "phone": "Teléfono",
            "email": "Correo",
        }
