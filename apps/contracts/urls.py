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

    # Generar Orden de Instalación desde el resumen de contratación
    path(
        "customers/<int:customer_pk>/contracts/<int:pk>/generate-installation/",
        views.InstallationWorkOrderCreateView.as_view(),
        name="generate_installation_order",
    ),

    # Comprobante de la Orden de Instalación generada desde este contrato.
    #
    # Pantalla de solo lectura, propia de contracts: no reimplementa nada
    # del dominio de work_orders, solo presenta los datos de la orden más
    # reciente de la suscripción del contrato (ver ContractSummaryView).
    path(
        "customers/<int:customer_pk>/contracts/<int:pk>/installation-order/",
        views.InstallationOrderReceiptView.as_view(),
        name="installation_order_receipt",
    ),
]
