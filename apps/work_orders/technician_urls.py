from django.urls import path

from .technician_views import TechnicianPortalView


app_name = "technician_portal"


urlpatterns = [
    path("", TechnicianPortalView.as_view(), name="home"),
]
