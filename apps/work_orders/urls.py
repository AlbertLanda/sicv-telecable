from django.urls import path

from . import views


app_name = "work_orders"


urlpatterns = [

    path(
        "customers/<int:customer_pk>/orders/create/",
        views.WorkOrderCreateView.as_view(),
        name="order_create",
    ),

]