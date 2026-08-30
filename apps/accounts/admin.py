from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """
    Administración del usuario del SICV.

    Extiende el UserAdmin estándar de Django (que ya trae contraseña,
    permisos, grupos y superusuario) en vez de reemplazarlo, y solo
    suma los campos propios del proyecto: rol, sede y oficina. Sin
    este registro no hay forma de ver ni editar usuarios desde el
    admin -el modelo existe, pero nadie lo expone.
    """

    list_display = (
        "username",
        "get_full_name",
        "role",
        "branch",
        "is_active",
        "is_staff",
    )

    list_filter = (
        "role",
        "branch",
        "is_active",
        "is_staff",
    )

    search_fields = (
        "username",
        "first_name",
        "last_name",
        "email",
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
                ),
            },
        ),
    )

    # Mismo criterio al crear un usuario nuevo desde el admin: los campos
    # estándar (username/contraseñas) más el rol, que es lo mínimo para que
    # el usuario sirva de algo en el sistema.
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "SICV",
            {
                "fields": (
                    "role",
                    "branch",
                    "office",
                ),
            },
        ),
    )
