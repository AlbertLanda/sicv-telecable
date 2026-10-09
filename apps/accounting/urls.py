from django.urls import path
from . import views

app_name = "accounting"
urlpatterns = [
    path("", views.workspace, name="workspace"),
    path("importar/", views.import_view, name="import"),
    path("documentos/<int:pk>/", views.document_view, name="document"),
    path("accesos/", views.access_view, name="access"),
    path("plantilla-rvie/", views.rvie_template, name="rvie_template"),
    path("ejemplo/", views.demo_view, name="demo"),
]
