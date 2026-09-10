from django.urls import path

from . import legacy_views, print_views, scheduling_views, views


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

    # Registrar un incidente para un cliente. La vista valida que el cliente
    # tenga un servicio activo y que la sede del operador coincida con la del cliente.
    path(
        "customers/<int:customer_pk>/incidents/create/",
        views.IncidentCreateView.as_view(),
        name="incident_create",
    ),

    # Asignación de un técnico a una orden. Solo ATC puede asignar; el técnico no. La asignación no borra la OT, solo la marca como ASSIGNED y registra la fecha y el técnico asignado. La OT asignada no puede reprogramarse ni atenderse por otro técnico.
    path(
        "<int:pk>/incident/start/",
        views.IncidentStartAttentionView.as_view(),
        name="incident_start",
    ),

    path(
        "<int:pk>/incident/close/",
        views.IncidentCloseView.as_view(),
        name="incident_close",
    ),

    # Presentación administrativa de la OT emitida. Deliberadamente excluye
    # ficha técnica, evidencias y liquidación para separar solicitud initial
    # de la ejecución registrada después por el técnico.
    path(
        "<int:pk>/initial/",
        print_views.WorkOrderInitialPrintView.as_view(),
        name="initial_print",
    ),

    # Compatibilidad temporal con enlaces antiguos. La asignación manual web
    # está retirada: este endpoint no acepta ningún técnico ni cambia estado.
    # La única adjudicación operativa ocurre cuando el técnico toma una OT
    # disponible desde el canal técnico /claim/.
    path(
        "<int:pk>/assign/",
        legacy_views.RetiredWebAssignmentView.as_view(),
        name="assign",
    ),

    # Inicio web histórico. El canal técnico dispone de su endpoint propio.
    path(
        "<int:pk>/start/",
        views.WorkOrderStartAttentionView.as_view(),
        name="start",
    ),


    # Anulación de una orden de trabajo. Solo ATC puede anular; el técnico no. La anulación no borra la OT, solo la marca como CANCELLED y registra la fecha y el motivo. La OT cancelada no puede reprogramarse ni atenderse.
    path(
        "<int:pk>/cancel/",
        views.WorkOrderCancelView.as_view(),
        name="cancel",
    ),

    # Ficha única de la orden: la misma pantalla sirve a ATC (solo lectura)
    # y al técnico asignado (además completa ficha técnica y evidencias).
    path(
        "<int:pk>/",
        views.WorkOrderDetailView.as_view(),
        name="detail",
    ),
]
