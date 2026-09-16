from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import PasswordChangeForm

from apps.accounts.models import User
from apps.organization.models import Office


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
    desde la gestión de Personal.
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


class OfficeSelect(forms.Select):
    """Añade la sede de cada oficina para poder filtrarla en el navegador."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-branch"] = str(instance.branch_id)
        return option


class OfficeSelectMultiple(forms.SelectMultiple):
    """Versión múltiple del selector de oficinas físicas por sede."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-branch"] = str(instance.branch_id)
        return option


class PersonnelForm(forms.ModelForm):
    """Datos operativos que Administración necesita manejar en el SICV.

    No expone grupos, permisos individuales, staff ni superusuario. Esa capa
    queda reservada a la administración técnica. Las oficinas habilitadas son
    solo ventanillas físicas; los depósitos se comparten automáticamente con ATC.
    """

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "role",
            "branch",
            "office",
            "allowed_offices",
            "is_active",
        ]
        labels = {
            "username": "Usuario",
            "first_name": "Nombres",
            "last_name": "Apellidos",
            "email": "Correo",
            "phone": "Teléfono",
            "role": "Rol",
            "branch": "Sede",
            "office": "Oficina principal",
            "allowed_offices": "Oficinas habilitadas para efectivo",
            "is_active": "Usuario activo",
        }
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "branch": forms.Select(attrs={"class": "form-select"}),
            "office": OfficeSelect(attrs={"class": "form-select"}),
            "allowed_offices": OfficeSelectMultiple(
                attrs={"class": "form-select", "size": "7"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, actor=None, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)

        physical_offices = Office.objects.filter(
            is_active=True,
            is_deposit=False,
        ).select_related("branch").order_by("branch__name", "name", "pk")

        self.fields["office"].queryset = physical_offices
        self.fields["allowed_offices"].queryset = physical_offices
        self.fields["office"].required = False
        self.fields["allowed_offices"].required = False
        self.fields["email"].required = False
        self.fields["phone"].required = False

        # Un administrador operativo puede gestionar personal, pero crear o
        # asignar nuevas cuentas ADMIN queda reservado al superusuario. Así
        # podemos tener un administrador del SICV y, por encima, una cuenta
        # administrativa con permisos ampliados.
        if actor is not None and not actor.is_superuser:
            self.fields["role"].choices = [
                choice
                for choice in User.Role.choices
                if choice[0] != User.Role.ADMIN
            ]

        self.fields["allowed_offices"].help_text = (
            "Solo aplica a Atención al Cliente. Los depósitos de la sede se "
            "habilitan automáticamente y no necesitan marcarse aquí."
        )

    def clean(self):
        cleaned = super().clean()
        branch = cleaned.get("branch")
        office = cleaned.get("office")
        allowed = cleaned.get("allowed_offices")
        role = cleaned.get("role")

        if self.actor is not None and not self.actor.is_superuser and role == User.Role.ADMIN:
            self.add_error("role", "Solo un superusuario puede asignar el rol Administrador.")

        if office and branch and office.branch_id != branch.pk:
            self.add_error("office", "La oficina principal debe pertenecer a la sede seleccionada.")

        if office and office.is_deposit:
            self.add_error("office", "El depósito no puede ser una oficina principal.")

        if allowed is not None and branch:
            invalid = [item for item in allowed if item.branch_id != branch.pk or item.is_deposit]
            if invalid:
                self.add_error(
                    "allowed_offices",
                    "Todas las oficinas habilitadas deben ser ventanillas físicas de la sede seleccionada.",
                )

        return cleaned

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and user.role != User.Role.ATC:
            user.allowed_offices.clear()
        return user


class PersonnelCreateForm(PersonnelForm):
    password1 = forms.CharField(
        label="Contraseña inicial",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirmar contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Las contraseñas no coinciden.")

        if password2:
            password_validation.validate_password(password2, self.instance)

        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])

        if commit:
            user.save()
            self.save_m2m()
            if user.role != User.Role.ATC:
                user.allowed_offices.clear()

        return user
