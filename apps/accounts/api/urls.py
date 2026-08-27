from django.urls import path

from . import views


# Namespace propio del canal de API. Las rutas web de sesión (login/logout de
# ATC y despacho) siguen en config/urls.py y no se ven afectadas.
app_name = "technicians_api"


urlpatterns = [

    # Autenticación del técnico.
    #
    # Único endpoint sin token de toda la API. Devuelve el token si las
    # credenciales son válidas y el usuario es un técnico activo.
    path(
        "login/",
        views.TechnicianLoginView.as_view(),
        name="login",
    ),

    # Identidad del técnico autenticado.
    #
    # Endpoint protegido de referencia para verificar que el token funciona.
    # No es un endpoint operativo: «mis órdenes», iniciar atención, atender y
    # liquidar llegan en los días 2 a 6 del bloque.
    path(
        "me/",
        views.TechnicianMeView.as_view(),
        name="me",
    ),

]
