from django.urls import path

from . import views


app_name = "work_orders"


urlpatterns = [

    # Tablero de programacion: las ordenes abiertas de la sede por dia.
    #
    # Las columnas son fechas, no estados. Solo lectura salvo el arrastre,
    # que va contra reprogramar/ y exige su propio permiso.
    path(
        "schedule/",
        views.WorkOrderScheduleBoardView.as_view(),
        name="schedule_board",
    ),

    # Reprogramar una orden. Endpoint JSON del arrastre del tablero: no
    # renderiza nada y delega toda la regla en WorkOrder.reprogram().
    path(
        "<int:pk>/reschedule/",
        views.WorkOrderRescheduleView.as_view(),
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

    # Asignar una orden de trabajo pendiente a un técnico.
    path(
        "<int:pk>/assign/",
        views.WorkOrderAssignView.as_view(),
        name="assign",
    ),

    # Iniciar la atención de una orden ya despachada.
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
