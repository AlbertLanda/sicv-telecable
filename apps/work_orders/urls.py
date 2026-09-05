from django.urls import path

from . import scheduling_views, views


app_name = "work_orders"


urlpatterns = [

    # Tablero de programación: las órdenes abiertas de la sede por día.
    # No asigna técnicos; organiza cuándo se espera atender cada OT.
    path(
        "schedule/",
        scheduling_views.WorkOrderScheduleBoardView.as_view(),
        name="schedule_board",
    ),

    # Reprogramar una orden desde el tablero. Una OT PENDING puede cambiar de
    # fecha sin que nadie tenga que tomarla primero; sigue PENDING hasta que
    # un técnico la reclame desde la API técnica.
    path(
        "<int:pk>/reschedule/",
        scheduling_views.WorkOrderRescheduleView.as_view(),
        name="reschedule",
    ),

    # Registrar una nueva orden de trabajo para un cliente.
    #
    # El cliente viaja en la ruta, no en el cuerpo del POST: la vista lo
    # resuelve en servidor y el formulario solo ofrece opciones de su ámbito.
    path(
        "customers/<int:customer_pk>/create/",
        views.WorkOrderCreateView.as_view(),
        name="create",
    ),

    # Ruta web histórica de asignación. Se conserva de momento para no romper
    # referencias existentes; el flujo operativo vigente es que el técnico
    # toma la OT desde /api/technicians/work-orders/<id>/claim/.
    path(
        "<int:pk>/assign/",
        views.WorkOrderAssignView.as_view(),
        name="assign",
    ),

    # Inicio web histórico. El canal técnico dispone de su endpoint propio.
    path(
        "<int:pk>/start/",
        views.WorkOrderStartAttentionView.as_view(),
        name="start",
    ),

    # Ficha única de la orden: la misma pantalla sirve a ATC (solo lectura)
    # y al técnico asignado (además completa ficha técnica y evidencias).
    path(
        "<int:pk>/",
        views.WorkOrderDetailView.as_view(),
        name="detail",
    ),
]
