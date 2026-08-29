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

]
