from django.urls import path

from . import field_views, views


# Namespace propio de la API de órdenes. Las rutas web del módulo
# (`work_orders:*`) siguen intactas en apps/work_orders/urls.py.
app_name = "work_orders_api"


urlpatterns = [

    # Órdenes disponibles: OT sin dueño que el técnico puede tomar.
    path(
        "available/",
        views.AvailableWorkOrderListView.as_view(),
        name="available",
    ),

    # Mis órdenes: OT asignadas al técnico autenticado.
    path(
        "",
        views.MyWorkOrderListView.as_view(),
        name="my_orders",
    ),

    # Detalle de una OT propia.
    path(
        "<int:pk>/",
        views.MyWorkOrderDetailView.as_view(),
        name="my_order_detail",
    ),

    # El técnico toma una OT disponible; queda ASSIGNED.
    path(
        "<int:pk>/claim/",
        views.ClaimWorkOrderView.as_view(),
        name="claim",
    ),

    # Declara el inicio real de la atención; queda IN_PROGRESS.
    path(
        "<int:pk>/start/",
        field_views.StartWorkOrderView.as_view(),
        name="start",
    ),

    # Ficha técnica editable durante IN_PROGRESS: NAP, borne, MAC/equipo,
    # precinto y observaciones. Es la misma ficha que ATC consulta en web.
    path(
        "<int:pk>/field-sheet/",
        field_views.FieldSheetView.as_view(),
        name="field_sheet",
    ),

    # Evidencias de campo de la misma OT.
    path(
        "<int:pk>/evidences/",
        field_views.WorkOrderEvidenceListCreateView.as_view(),
        name="evidences",
    ),

]
