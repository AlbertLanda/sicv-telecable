from django.urls import path

from . import views


app_name = "reports"


urlpatterns = [
    path(
        "ventas/",
        views.SalesReportView.as_view(),
        name="sales",
    ),
    path(
        "materiales/",
        views.MaterialReportView.as_view(),
        name="materials",
    ),

    # La hoja, en su propia URL. Se abre en una pestaña nueva y por eso tiene
    # que poder pegarse, recargarse y guardarse: el periodo y el alcance
    # viajan en la barra de direcciones, no en un POST que solo existe una vez.
    path(
        "materiales/listar/",
        views.MaterialReportListView.as_view(),
        name="materials_list",
    ),
]
