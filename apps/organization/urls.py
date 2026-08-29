from django.urls import path

from . import views


app_name = "organization"


urlpatterns = [

    # Cambiar la sede desde la que se consulta.
    #
    # No cambia la sede asignada al usuario: solo el ámbito de esta sesión,
    # para que ATC pueda atender a un abonado de otra sede sin derivarlo.
    path(
        "sede-activa/",
        views.set_active_branch,
        name="set_active_branch",
    ),

    # Cambiar la oficina desde la que se atiende.
    #
    # Hoy solo contexto visible en la barra. La necesitará el flujo de caja,
    # donde cada cobro se hace en una oficina concreta.
    path(
        "oficina-activa/",
        views.set_active_office,
        name="set_active_office",
    ),

]
