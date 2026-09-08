from django.urls import path

from . import views


app_name = "services"


urlpatterns = [
    path(
        "customers/<int:customer_pk>/subscriptions/create/",
        views.SubscriptionCreateView.as_view(),
        name="subscription_create",
    ),
    path(
        "customers/<int:customer_pk>/subscriptions/<int:subscription_pk>/summary/",
        views.SubscriptionSummaryView.as_view(),
        name="subscription_summary",
    ),

    # ------------------------------------------------------------------
    # Configurar > Servicios
    # ------------------------------------------------------------------
    path(
        "configurar/servicios/",
        views.ServiceTypeListView.as_view(),
        name="servicetype_list",
    ),
    path(
        "configurar/servicios/nuevo/",
        views.ServiceTypeCreateView.as_view(),
        name="servicetype_create",
    ),
    path(
        "configurar/servicios/<int:pk>/editar/",
        views.ServiceTypeUpdateView.as_view(),
        name="servicetype_edit",
    ),

    # ------------------------------------------------------------------
    # Configurar > Planes
    # ------------------------------------------------------------------
    path(
        "configurar/planes/",
        views.PlanListView.as_view(),
        name="plan_list",
    ),
    path(
        "configurar/planes/nuevo/",
        views.PlanCreateView.as_view(),
        name="plan_create",
    ),
    path(
        "configurar/planes/<int:pk>/editar/",
        views.PlanUpdateView.as_view(),
        name="plan_edit",
    ),
]