"""Rutas del canal de logística.

Namespace propio y prefijo propio (`/api/logistics/`). No cuelga de
`/api/technicians/` porque no es el mismo canal: cambia quién consume -un
sistema, no una app-, cambia cómo se autoriza -permiso de Django, no rol- y
cambia el ritmo de los cambios. Compartir prefijo haría que una regla puesta
para uno alcanzara al otro sin que nadie lo hubiera decidido.
"""

from django.urls import path

from . import views


app_name = "logistics_api"


urlpatterns = [

    # El detalle del periodo, una fila por movimiento de material.
    path(
        "material-movements/",
        views.MaterialMovementListView.as_view(),
        name="material_movements",
    ),

    # Reconciliación: qué ids siguen vigentes, para detectar lo borrado.
    path(
        "material-movements/ids/",
        views.MaterialMovementIdListView.as_view(),
        name="material_movement_ids",
    ),

    # La marca de agua del periodo, para la siguiente sincronización
    # incremental.
    path(
        "material-movements/watermark/",
        views.MaterialMovementWatermarkView.as_view(),
        name="material_movement_watermark",
    ),

]
