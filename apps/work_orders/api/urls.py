from django.urls import path

from . import contract_views, field_views, nap_views, views


app_name = "work_orders_api"


urlpatterns = [
    path("available/", views.AvailableWorkOrderListView.as_view(), name="available"),
    path("", views.MyWorkOrderListView.as_view(), name="my_orders"),
    path("<int:pk>/", views.MyWorkOrderDetailView.as_view(), name="my_order_detail"),
    path("<int:pk>/claim/", views.ClaimWorkOrderView.as_view(), name="claim"),
    path("<int:pk>/start/", field_views.StartWorkOrderView.as_view(), name="start"),
    path("<int:pk>/complete/", field_views.CompleteWorkOrderView.as_view(), name="complete"),
    path("<int:pk>/liquidate/", field_views.LiquidateWorkOrderView.as_view(), name="liquidate"),
    path(
        "<int:pk>/field-sheet/",
        nap_views.CatalogFieldSheetView.as_view(),
        name="field_sheet",
    ),
    path(
        "<int:pk>/naps/",
        nap_views.NetworkAccessPointSearchView.as_view(),
        name="nap_search",
    ),
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
    # La contrata del abonado: el mismo contrato que imprime SICV, con la
    # firma que se recoge en el domicilio. Ver docs/contrata_firma_campo.md.
    path(
        "<int:pk>/contract/",
        contract_views.WorkOrderContractView.as_view(),
        name="contract",
    ),
    path(
        "<int:pk>/contract/document/",
        contract_views.WorkOrderContractDocumentView.as_view(),
        name="contract_document",
    ),
    path(
        "<int:pk>/contract/signature/",
        contract_views.WorkOrderContractSignatureView.as_view(),
        name="contract_signature",
    ),
    path(
        "<int:pk>/evidences/",
        field_views.WorkOrderEvidenceListCreateView.as_view(),
        name="evidences",
    ),
]
