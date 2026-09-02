"""
Permisos funcionales del canal de API del técnico.

El permiso global del proyecto (`IsAuthenticated`, día 1) responde a «¿sé
quién eres?». Este módulo responde a «¿eres quien puede operar en este
canal?», que es una pregunta distinta y se resuelve por separado.
"""

from rest_framework.permissions import BasePermission

from apps.accounts.services import is_active_technician


class IsActiveTechnician(BasePermission):
    """Exige que el usuario autenticado sea un técnico activo.

    Capa adicional sobre `IsAuthenticated`, no un reemplazo: el token
    identifica al usuario, y este permiso decide si ese usuario puede usar
    los endpoints operativos del canal técnico.

    No reimplementa la regla: delega en `is_active_technician()`, el mismo
    predicado que usa el login. Y la evalúa en **cada petición**, no solo al
    emitir el token — que es lo que cierra el hueco de un token vigente cuyo
    dueño fue desactivado o cambiado de rol después de autenticarse (el token
    del canal técnico no caduca; ver docs/api_technician_auth.md).
    """

    message = "Se requiere un usuario con rol técnico activo."

    def has_permission(self, request, view):
        return is_active_technician(request.user)
