from django.urls import path

from . import views


app_name = "customers"


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
        views.CustomerInitialCreateView.as_view(),
        name="create",
    ),

    # Consulta AJAX de solo lectura (RENIEC/SUNAT) usada por el botón
    # "Obtener datos" de la Pantalla 3.
    path(
        "lookup-document/",
        views.CustomerDocumentLookupView.as_view(),
        name="lookup_document",
    ),

    # Registrar datos generales del cliente
    path(
        "create/general/",
        views.CustomerGeneralDataView.as_view(),
        name="general_create",
    ),

    # Editar datos generales del cliente
    path(
        "<int:customer_pk>/edit/general/",
        views.CustomerGeneralDataEditView.as_view(),
        name="general_edit",
    ),

    # Registrar dirección
    path(
        "<int:customer_pk>/addresses/create/",
        views.CustomerAddressCreateView.as_view(),
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

    # Ficha del cliente
    path(
        "<int:pk>/",
        views.CustomerDetailView.as_view(),
        name="detail",
    ),
]