"""Quién puede leer el feed de movimientos de material.

El canal del técnico resuelve su permiso por rol (`IsActiveTechnician`):
allí la pregunta es «¿eres un técnico en ejercicio?», porque los endpoints
escriben sobre la orden que ese técnico está atendiendo.

Aquí la pregunta es otra y se resuelve con el permiso de Django, no con el
rol. Quien puede consultar un movimiento de material en la ficha de una orden
puede consultarlo también en una lista, venga de la pantalla web o de otro
sistema — es el mismo criterio que ya aplica `MaterialReportPermissionMixin` a
la hoja en pantalla, y sostenerlo con un rol daría dos respuestas distintas a
la misma pregunta.

En la práctica esto significa que el usuario de servicio de logística no
necesita un rol especial: necesita el permiso, y se le concede como a
cualquier otro usuario (ver docs/api_logistics_materials.md).
"""

from rest_framework.permissions import BasePermission


MATERIAL_MOVEMENT_PERMISSION = "inventory.view_workordermaterialmovement"


class CanReadMaterialMovements(BasePermission):
    """Exige el permiso de consulta de movimientos de material.

    Se evalúa en **cada petición** y no solo al emitir el token. El token de
    DRF no caduca, así que sin esta comprobación por petición un usuario al
    que se le retiró el permiso seguiría descargando el feed con el token que
    ya tenía en su poder.
    """

    message = "Se requiere el permiso de consulta de movimientos de material."

    def has_permission(self, request, view):
        return request.user.has_perm(MATERIAL_MOVEMENT_PERMISSION)
