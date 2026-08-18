from django.urls import path
from . import views

app_name = 'customers'

urlpatterns = [
    # Ruta: /customers/search/
    path('search/', views.CustomerSearchView.as_view(), name='search'),
    
    # Ruta: /customers/1/ (Ficha del cliente)
    path('<int:pk>/', views.CustomerDetailView.as_view(), name='detail'),
]