from django.urls import path

from . import views

app_name = "equipment"
urlpatterns = [
    path("", views.EquipmentListView.as_view(), name="list"),
    path("registrar/", views.EquipmentCreateView.as_view(), name="create"),
    path("<int:pk>/", views.EquipmentDetailView.as_view(), name="detail"),
    path("<int:pk>/revisar/", views.EquipmentReviewView.as_view(), name="review"),
    path("abonado/<int:customer_pk>/", views.CustomerEquipmentView.as_view(), name="customer"),
    path("abonado/<int:customer_pk>/asignar/", views.EquipmentAssignView.as_view(), name="assign"),
    path("asignacion/<int:assignment_pk>/retirar/", views.EquipmentRemoveView.as_view(), name="remove"),
]
