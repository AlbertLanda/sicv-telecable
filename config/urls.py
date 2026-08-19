from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    # Raíz del sistema → Login
    path(
        '',
        RedirectView.as_view(
            pattern_name='login',
            permanent=False,
        ),
    ),

    # Administración
    path('admin/', admin.site.urls),

    # Autenticación
    path(
        'accounts/login/',
        auth_views.LoginView.as_view(
            template_name='registration/login.html',
        ),
        name='login',
    ),

    path(
        'accounts/logout/',
        auth_views.LogoutView.as_view(),
        name='logout',
    ),

    # Módulo de clientes
    path(
        'customers/',
        include('apps.customers.urls'),
    ),

    # Módulo de servicios
    path(
        'services/',
        include('apps.services.urls'),
    ),

   # Módulo de contratos
    path(
        'contracts/',
        include('apps.contracts.urls'),
    ),

    # Módulo de órdenes de trabajo
    path(
        'work-orders/',
        include('apps.work_orders.urls'),
    ), 
]
