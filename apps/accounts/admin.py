from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import User
from apps.organization.models import Office


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """
    Administración del usuario del SICV.

    Extiende el UserAdmin estándar de Django (que ya trae contraseña,
    permisos, grupos y superusuario) en vez de reemplazarlo, y solo
    suma los campos propios del proyecto: rol, sede y oficinas. Sin
    este registro no hay forma de ver ni editar usuarios desde el
    admin -el modelo existe, pero nadie lo expone.
    """

    list_display = (
        "username",
        "get_full_name",
        "role",
        "branch",
        "is_salesperson",
        "is_active",
        "is_staff",
    )

    list_filter = (
        "role",
        "branch",
        "is_salesperson",
        "is_active",
        "is_staff",
    )

    search_fields = (
        "username",
        "first_name",
        "last_name",
        "email",
    )

    filter_horizontal = DjangoUserAdmin.filter_horizontal + (
        "allowed_offices",
    )

    # Los fieldsets del UserAdmin estándar ya cubren usuario, contraseña,
    # datos personales, permisos y fechas importantes. Se agrega un bloque
    # propio del SICV al final en vez de reescribir los existentes.
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "SICV",
            {
                "fields": (
                    "role",
                    "branch",
                    "office",
                    "allowed_offices",
                    "is_salesperson",
                ),
            },
        ),
    )

    # Mismo criterio al crear un usuario nuevo desde el admin: los campos
    # estándar (username/contraseñas) más el rol y su ámbito operativo.
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "SICV",
            {
                "fields": (
                    "role",
                    "branch",
                    "office",
                    "allowed_offices",
                    "is_salesperson",
                ),
            },
        ),
    )

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "allowed_offices":
            # El administrador solo asigna cajas/ventanillas físicas. Los
            # depósitos son compartidos y se habilitan automáticamente.
            kwargs["queryset"] = Office.objects.filter(
                is_active=True,
                is_deposit=False,
            ).order_by("branch__name", "name")

        return super().formfield_for_manytomany(db_field, request, **kwargs)
