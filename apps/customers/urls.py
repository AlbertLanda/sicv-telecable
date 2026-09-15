from django.contrib.auth.decorators import permission_required
from django.urls import path

from . import dashboard_views, views


app_name = "customers"


def require(permission, view):
    """Protege acciones mutables también cuando se abre la URL directamente."""
    return permission_required(permission, raise_exception=True)(view.as_view())


urlpatterns = [

    # Consulta de clientes
    path(
        "search/",
        views.CustomerSearchView.as_view(),
        name="search",
    ),

    # Registrar nuevo cliente
    path(
        "create/",
        require("customers.add_customer", views.CustomerInitialCreateView),
        name="create",
    ),

    # Consulta AJAX de solo lectura (RENIEC/SUNAT) usada por el botón
    # "Obtener datos" de la Pantalla 3.
    path(
        "lookup-document/",
        views.CustomerDocumentLookupView.as_view(),
        name="lookup_document",
    ),

    # Consulta AJAX de suministro eléctrico
    path(
        "lookup-supply/",
        views.SupplyLookupView.as_view(),
        name="lookup_supply",
    ),

    # Registrar datos generales del cliente
    path(
        "create/general/",
        require("customers.add_customer", views.CustomerGeneralDataView),
        name="general_create",
    ),

    # Editar datos generales del cliente
    path(
        "<int:customer_pk>/edit/general/",
        require("customers.change_customer", views.CustomerGeneralDataEditView),
        name="general_edit",
    ),

    # Registrar dirección
    path(
        "<int:customer_pk>/addresses/create/",
        require("customers.add_customeraddress", views.CustomerAddressCreateView),
        name="address_create",
    ),

    # Usar cliente existente
    path(
        "<int:pk>/use/",
        views.CustomerUseView.as_view(),
        name="use",
    ),

    # Propuesta visual (solo lectura) del futuro formulario de OT.
    # No crea ni guarda órdenes de trabajo.
    path(
        "<int:pk>/work-orders/new-preview/",
        views.CustomerWorkOrderUIPreviewView.as_view(),
        name="work_order_ui_preview",
    ),

    # Ficha del cliente. Cada pestaña es su propia pantalla: el abonado visto
    # desde un ángulo distinto, no una sección de una página gigante. Las de
    # cobranza -deuda, pagos, comprobantes- viven en apps.payments.
    path(
        "<int:pk>/",
        dashboard_views.CustomerDashboardDetailView.as_view(),
        name="detail",
    ),
    path(
        "<int:pk>/ordenes/",
        dashboard_views.CustomerOrdersTabView.as_view(),
        name="orders",
    ),
    path(
        "<int:pk>/actividad/",
        dashboard_views.CustomerActivityTabView.as_view(),
        name="activity",
    ),
]
