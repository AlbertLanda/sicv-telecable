"""
Permisos de acción de la API de órdenes del canal técnico.

Separación deliberada respecto de `apps/accounts/api/permissions.py`: aquel
responde «¿puedes operar en el canal técnico?» (`IsActiveTechnician`), y este
responde «¿puedes ejecutar **esta** acción sobre una orden?». Son preguntas
distintas y se declaran por separado, igual que en la web, donde ser técnico y
tener `assign_workorder` tampoco son lo mismo.
"""

from rest_framework.permissions import BasePermission


# Permiso funcional exigido para tomar una orden — **bloqueo B3, abierto**.
#
# `None` significa: hoy la toma no exige ningún permiso Django adicional, y la
# autorización es el propio permiso de canal (`IsActiveTechnician`). No es un
# olvido, es lo único que puede afirmarse sin inventar una regla:
#
# 1. **Reutilizar `assign_workorder` (propuesta del día 1) tiene un efecto
#    lateral que no se había medido.** Es el mismo permiso que gobierna la
#    bandeja de despacho web (`WorkOrderAssignView.permission_required`,
#    `views.py:148`) y el que decide si se pinta la acción «Asignar» en las
#    plantillas. Concederlo al grupo Técnico para habilitar la toma le daría
#    además la potestad de asignar **cualquier** orden a **cualquier** técnico
#    desde la web. La toma es lo contrario: el técnico solo puede tomar para
#    sí mismo y solo del pool sin dueño. Además `models.py:610` documenta la
#    intención opuesta —que la app del técnico pueda recibir `start_workorder`
#    «sin arrastrar assign_workorder»—, así que reutilizarlo contradice el
#    criterio con el que se separaron los permisos.
#
# 2. **Crear `claim_workorder` exige migración de `Meta.permissions`**, que
#    por regla del sprint requiere aprobación, y hasta que alguien lo conceda
#    dejaría la toma en 403 para todos los técnicos.
#
# Mientras negocio decida, la autorización real de la toma no queda en el
# aire: la sostienen el permiso de canal (solo un técnico activo entra), el
# filtro de disponibilidad —solo se puede tomar lo que no tiene dueño— y el
# hecho de que el técnico sale de `request.user` y nunca del cuerpo.
#
# Cerrar B3 es cambiar **esta línea** por el nombre del permiso
# (`"work_orders.claim_workorder"` o `"work_orders.assign_workorder"`): no hay
# que tocar la vista, ni la ruta, ni el serializador. Hay una prueba que fija
# ese cableado (`test_functional_permission_gates_the_claim`).
CLAIM_PERMISSION = None


class CanClaimWorkOrder(BasePermission):
    """Exige el permiso funcional de la toma, cuando exista uno.

    Se evalúa **antes** de resolver la orden, igual que en la web: si el orden
    fuera el inverso, un técnico sin el permiso recibiría una respuesta
    distinta según si el id existe o no, y esa diferencia le diría cuáles
    existen. Con este orden recibe 403 para cualquier id y no aprende nada.

    No se usa `DjangoModelPermissions`, que mapea permisos a métodos HTTP
    sobre un modelo (`add`/`change`/`delete`): tomar una orden no es
    «modificar una orden», es una acción del proceso. Traducirla a
    `change_workorder` diluiría justo la distinción que el módulo mantiene.
    """

    message = "No tiene permiso para tomar órdenes de trabajo."

    def has_permission(self, request, view):
        if CLAIM_PERMISSION is None:
            return True

        return request.user.has_perm(CLAIM_PERMISSION)
