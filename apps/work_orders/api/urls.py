from django.urls import path

from . import field_views, views


app_name = "work_orders_api"


urlpatterns = [
    path("available/", views.AvailableWorkOrderListView.as_view(), name="available"),
    path("", views.MyWorkOrderListView.as_view(), name="my_orders"),
    path("<int:pk>/", views.MyWorkOrderDetailView.as_view(), name="my_order_detail"),
    path("<int:pk>/claim/", views.ClaimWorkOrderView.as_view(), name="claim"),
    path("<int:pk>/start/", field_views.StartWorkOrderView.as_view(), name="start"),
    path("<int:pk>/field-sheet/", field_views.FieldSheetView.as_view(), name="field_sheet"),
    path(
        "<int:pk>/field-materials/",
        field_views.WorkOrderMaterialMovementView.as_view(),
        name="field_materials",
    ),
    path(
        "<int:pk>/materials/",
        field_views.InstallationMaterialUsageListCreateView.as_view(),
        name="materials",
    ),
    path(
        "<int:pk>/evidences/",
        field_views.WorkOrderEvidenceListCreateView.as_view(),
        name="evidences",
    ),
]
