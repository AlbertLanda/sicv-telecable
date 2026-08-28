"""
Permisos de acción de la API de órdenes del canal técnico.

Separación deliberada respecto de `apps/accounts/api/permissions.py`: aquel
responde «¿puedes operar en el canal técnico?» (`IsActiveTechnician`), y este
responde «¿puedes ejecutar **esta** acción sobre una orden?». Son preguntas
distintas y se declaran por separado, igual que en la web, donde ser técnico y
tener `start_workorder` tampoco son lo mismo.
"""

from rest_framework.permissions import BasePermission


class CanStartWorkOrder(BasePermission):
    """Exige el permiso Django `work_orders.start_workorder`.

    Es **el mismo permiso funcional que ya usa la web** (migración 0011,
    `WorkOrderStartAttentionView.permission_required`). No se creó uno nuevo
    para la API: si mañana operaciones se lo retira a un técnico, se lo retira
    en los dos canales a la vez.

    No se usa `DjangoModelPermissions` porque mapea permisos a métodos HTTP
    sobre un modelo (`add`/`change`/`delete`), y aquí el permiso es funcional:
    iniciar la atención no es «modificar una orden», es una acción del proceso
    con su propio permiso. Traducirla a `change_workorder` diluiría justo la
    distinción que el módulo mantiene.

    Se evalúa **antes** de resolver la orden, igual que en la web: quien no
    puede iniciar recibe 403 para cualquier id, así que la ausencia del
    permiso no permite sondear con 404 qué órdenes existen.
    """

    message = "No tiene permiso para iniciar la atención de órdenes."

    def has_permission(self, request, view):
        return request.user.has_perm("work_orders.start_workorder")
