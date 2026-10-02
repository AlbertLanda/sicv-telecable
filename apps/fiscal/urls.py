from django.urls import path
from . import views

app_name = "fiscal"
urlpatterns = [
    path("empresas/<int:issuer_id>/conexion-ose/", views.OseConnectionView.as_view(), name="ose_connection"),
    path("borradores/<uuid:public_id>/prueba-ose/", views.OseSimulationCreateView.as_view(), name="ose_simulation_create"),
    path("pruebas-ose/<uuid:public_id>/", views.OseSimulationDetailView.as_view(), name="ose_simulation_detail"),
    path("pruebas-ose/<uuid:public_id>/ejecutar/", views.OseSimulationRunView.as_view(), name="ose_simulation_run"),
    path("", views.DraftListView.as_view(), name="list"),
    path("empresas/<int:issuer_id>/", views.ProfileView.as_view(), name="profile"),
    path("clientes/<int:customer_id>/preparar/", views.DraftCreateView.as_view(), name="create"),
    path("borradores/<uuid:public_id>/", views.DraftDetailView.as_view(), name="detail"),
    path("borradores/<uuid:public_id>/descartar/", views.DraftCancelView.as_view(), name="cancel"),
]
