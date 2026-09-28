from django.urls import path

from . import views


app_name = "audit"


urlpatterns = [
    path("actividad/", views.ActivityListView.as_view(), name="activity"),
]
