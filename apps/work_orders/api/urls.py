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

]
