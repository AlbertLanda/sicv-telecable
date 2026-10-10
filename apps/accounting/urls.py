from django.urls import path
from . import views
from . import bank_views
from . import revenue_views

app_name = "accounting"
urlpatterns = [
    path("recaudacion/", revenue_views.workspace, name="revenue"),
    path("recaudacion/alertas/<int:pk>/", revenue_views.rules, name="revenue_rules"),
    path("bancos/", bank_views.bank_workspace, name="bank_workspace"),
    path("bancos/<int:pk>/", bank_views.bank_account, name="bank_account"),
    path("bancos/<int:pk>/plantilla/", bank_views.bank_template, name="bank_template"),
    path("bancos/<int:pk>/exportar/", bank_views.bank_export, name="bank_export"),
    path("bancos/<int:account_pk>/movimientos/<int:pk>/", bank_views.bank_line, name="bank_line"),
    path("bancos/<int:account_pk>/extractos/<int:pk>/", bank_views.bank_source, name="bank_source"),
    path("", views.workspace, name="workspace"),
    path("importar/", views.import_view, name="import"),
    path("documentos/<int:pk>/", views.document_view, name="document"),
    path("accesos/", views.access_view, name="access"),
    path("plantilla-rvie/", views.rvie_template, name="rvie_template"),
    path("ejemplo/", views.demo_view, name="demo"),
]
