from django.urls import path

from . import views


# Namespace propio de la API de órdenes. Las rutas web del módulo
# (`work_orders:*`) siguen intactas en apps/work_orders/urls.py.
app_name = "work_orders_api"


urlpatterns = [

    # Órdenes disponibles: OT sin dueño que el técnico puede tomar.
    #
    # Se declara antes que `<int:pk>/` por costumbre defensiva: hoy el
    # convertidor `int` no captura «available», pero si algún día el detalle
    # pasara a `<str:...>` o a un slug, la ruta literal quedaría eclipsada.
    # Ponerla primero cuesta nada y elimina el escenario.
    path(
        "available/",
        views.AvailableWorkOrderListView.as_view(),
        name="available",
    ),

    # Mis órdenes: OT asignadas al técnico autenticado.
    #
    # Sin parámetros: el técnico sale de `request.user`, no de la petición.
    path(
        "",
        views.MyWorkOrderListView.as_view(),
        name="my_orders",
    ),

    # Detalle de una OT propia.
    #
    # El id viaja en la ruta, pero no decide de quién es la orden: el queryset
    # de la vista ya está filtrado por `request.user`, así que un id ajeno
    # responde 404 igual que uno inexistente.
    path(
        "<int:pk>/",
        views.MyWorkOrderDetailView.as_view(),
        name="my_order_detail",
    ),

    # Toma de una OT disponible: el técnico se adjudica trabajo sin dueño.
    #
    # Es la acción sobre un recurso concreto, así que va como sufijo del id y
    # no como una ruta suelta con el id en el cuerpo: el objeto de la acción
    # se lee en la URL. Mismo criterio que la web, que expone
    # `ordenes/<pk>/asignar/`.
    #
    # No eclipsa al detalle ni al revés: Django resuelve la ruta completa, y
    # `<int:pk>/` solo casa con la URL que termina en el id.
    path(
        "<int:pk>/claim/",
        views.ClaimWorkOrderView.as_view(),
        name="claim",
    ),

]
