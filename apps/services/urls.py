from django.contrib.auth.decorators import login_required, permission_required
from django.urls import path

from . import views


app_name = "services"


def require_authenticated_permission(permission, view):
    """Anónimo -> login; autenticado sin permiso -> 403."""
    protected = permission_required(
        permission,
        raise_exception=True,
    )(view.as_view())
    return login_required(protected)


urlpatterns = [
    path(
        "customers/<int:customer_pk>/subscriptions/create/",
        require_authenticated_permission(
            "services.add_subscription",
            views.SubscriptionCreateView,
        ),
        name="subscription_create",
    ),
    path(
        "customers/<int:customer_pk>/subscriptions/<int:subscription_pk>/seller/",
        require_authenticated_permission(
            "services.add_subscription",
            views.SubscriptionSellerUpdateView,
        ),
        name="subscription_seller",
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
