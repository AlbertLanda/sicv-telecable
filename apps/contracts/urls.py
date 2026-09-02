from django.urls import path

from . import views


app_name = "contracts"


urlpatterns = [

    # Registrar contrato para un cliente
    path(
        "customers/<int:customer_pk>/contracts/create/",
        views.ContractCreateView.as_view(),
        name="contract_create",
    ),

    # Resumen de contratación
    path(
        "customers/<int:customer_pk>/contracts/<int:pk>/summary/",
        views.ContractSummaryView.as_view(),
        name="contract_summary",
    ),
]
