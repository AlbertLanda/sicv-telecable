from django.urls import path

from . import views


app_name = "work_orders"


urlpatterns = [

    # Bandeja operativa de despacho.
    #
    # Listado de solo lectura: busca, filtra y enlaza al flujo de asignación.
    # No ejecuta ninguna transición por sí misma.
    path(
        "dispatch/",
        views.WorkOrderDispatchListView.as_view(),
        name="dispatch",
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
    #
    # La orden viaja en la ruta; el POST solo elige entre los técnicos que el
    # formulario ya acotó a la sede de esa orden.
    path(
        "<int:pk>/assign/",
        views.WorkOrderAssignView.as_view(),
        name="assign",
    ),

    # Iniciar la atención de una orden ya despachada.
    #
    # La orden viaja en la ruta y el POST solo lleva una observación: el
    # estado destino y la hora real de inicio los pone el dominio, no el
    # navegador. El GET únicamente confirma; nada cambia hasta el POST.
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
