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

    path(
        "create/general/",
        views.CustomerGeneralDataView.as_view(),
        name="general_create",
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

    # Ficha del cliente
    path(
        "<int:pk>/",
        views.CustomerDetailView.as_view(),
        name="detail",
    ),
]