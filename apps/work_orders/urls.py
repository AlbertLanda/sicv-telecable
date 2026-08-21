from django.urls import path

from . import views


app_name = "work_orders"


urlpatterns = [

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
]
