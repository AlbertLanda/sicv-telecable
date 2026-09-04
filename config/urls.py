from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    # Raíz del sistema → Login
    path(
        "",
        RedirectView.as_view(
            pattern_name="login",
            permanent=False,
        ),
    ),

    # Administración
    path("admin/", admin.site.urls),

    # Autenticación
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path(
        "accounts/logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),

    # Mi perfil y cambio de clave del propio usuario.
    path(
        "accounts/",
        include("apps.accounts.urls"),
    ),

    # Organización: sede activa de la sesión.
    path(
        "organizacion/",
        include("apps.organization.urls"),
    ),

    # Clientes
    path(
        "customers/",
        include("apps.customers.urls"),
    ),

    # Servicios
    path(
        "services/",
        include("apps.services.urls"),
    ),

    # Contratos
    path(
        "contracts/",
        include("apps.contracts.urls"),
    ),

    # Órdenes de trabajo
    path(
        "work-orders/",
        include("apps.work_orders.urls"),
    ),

    # Portal móvil/responsive del técnico. El shell HTML no usa la sesión
    # web de ATC; toda lectura y escritura real exige TokenAuthentication.
    path(
        "technician/",
        include("apps.work_orders.technician_urls"),
    ),

    # API del técnico (app/PWA) — canal separado del login web de sesión:
    # autenticación por token, sin cookies ni plantillas.
    #
    # Órdenes de trabajo del canal técnico: disponibles, mis órdenes y
    # detalle. Se declara antes que el include de identidad porque su prefijo
    # es más específico. Ver docs/api_technician_work_orders.md.
    path(
        "api/technicians/work-orders/",
        include("apps.work_orders.api.urls"),
    ),

    # Autenticación e identidad del técnico (login, me).
    # Ver docs/api_technician_auth.md.
    path(
        "api/technicians/",
        include("apps.accounts.api.urls"),
    ),

]


# Solo en desarrollo: en producción las evidencias las sirve el backend
# de almacenamiento definitivo, no Django.
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
