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
]