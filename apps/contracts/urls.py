from django.contrib.auth.decorators import login_required, permission_required
from django.urls import path

from . import print_views, views


app_name = "contracts"


def require_authenticated_permission(permission, view):
    """Anónimo -> login; autenticado sin permiso -> 403."""
    protected = permission_required(
        permission,
        raise_exception=True,
    )(view.as_view())
    return login_required(protected)


urlpatterns = [

    # Registrar contrato para un cliente
    path(
        "customers/<int:customer_pk>/contracts/create/",
        require_authenticated_permission(
            "contracts.add_contract",
            views.ContractCreateView,
        ),
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

    # Contrato de abonado en PDF, para imprimirlo y firmarlo.
    #
    # Se sirve con el mismo alcance que el resumen -el contrato tiene que
    # pertenecer al cliente de la URL- y sin permiso propio: quien puede
    # abrir el contrato puede imprimir el documento que lo describe.
    path(
        "customers/<int:customer_pk>/contracts/<int:pk>/documento/",
        print_views.ContractDocumentPdfView.as_view(),
        name="contract_document",
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
