from django.urls import path

from . import incident_noc, legacy_views, print_views, scheduling_views, views


app_name = "work_orders"


urlpatterns = [

    # Bandeja colaborativa de NOC. Todos los operadores autorizados ven la
    # misma cola; tomar/retomar una incidencia se resuelve de forma exclusiva
    # en el dominio para evitar atenciones cruzadas.
    path(
        "noc/incidents/",
        incident_noc.NocIncidentQueueView.as_view(),
        name="incident_noc_queue",
    ),
    path(
        "noc/incidents/notifications/",
        incident_noc.IncidentNotificationsView.as_view(),
        name="incident_notifications",
    ),

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

    # Registrar una incidencia para un cliente.
    path(
        "customers/<int:customer_pk>/incidents/create/",
        views.IncidentCreateView.as_view(),
        name="incident_create",
    ),

    # Ficha operativa NOC: responsabilidad actual, reprogramaciones,
    # trazabilidad e incidencias anteriores de la misma suscripción.
    path(
        "<int:pk>/incident/noc/",
        incident_noc.NocIncidentDetailView.as_view(),
        name="incident_noc_detail",
    ),

    # Se conserva el nombre `incident_start` para no romper enlaces ya
    # existentes, pero la acción ahora significa "Tomar incidencia".
    path(
        "<int:pk>/incident/start/",
        incident_noc.IncidentClaimView.as_view(),
        name="incident_start",
    ),
    path(
        "<int:pk>/incident/release/",
        incident_noc.IncidentReleaseView.as_view(),
        name="incident_release",
    ),
    path(
        "<int:pk>/incident/reschedule/",
        incident_noc.IncidentRescheduleView.as_view(),
        name="incident_reschedule",
    ),
    path(
        "<int:pk>/incident/resume/",
        incident_noc.IncidentResumeView.as_view(),
        name="incident_resume",
    ),
    path(
        "<int:pk>/incident/close/",
        incident_noc.IncidentNocCloseView.as_view(),
        name="incident_close",
    ),
    path(
        "<int:pk>/incident/cancel/",
        incident_noc.IncidentNocCancelView.as_view(),
        name="incident_cancel",
    ),

    # Presentación administrativa de la OT emitida. Deliberadamente excluye
    # ficha técnica, evidencias y liquidación para separar solicitud inicial
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

    # Anulación genérica de órdenes físicas. Las incidencias NOC usan la ruta
    # específica `/incident/cancel/`, que también cubre EN ATENCIÓN y
    # REPROGRAMADA sin mezclar esas reglas con el flujo de campo.
    path(
        "<int:pk>/cancel/",
        views.WorkOrderCancelView.as_view(),
        name="cancel",
    ),

    # Ficha única de la orden para el flujo general.
    path(
        "<int:pk>/",
        views.WorkOrderDetailView.as_view(),
        name="detail",
    ),
]
