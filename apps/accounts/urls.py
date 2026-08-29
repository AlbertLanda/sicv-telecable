from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .forms import StyledPasswordChangeForm


app_name = "accounts"


urlpatterns = [

    # Mi perfil: identidad de solo lectura + contacto editable.
    path(
        "perfil/",
        views.ProfileView.as_view(),
        name="profile",
    ),

    # Cambiar clave. Se usan las vistas estándar de Django
    # (ya validan la clave actual y la fuerza de la nueva) con
    # plantillas propias del proyecto, no las genéricas del admin.
    path(
        "clave/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change.html",
            form_class=StyledPasswordChangeForm,
            success_url=reverse_lazy("accounts:password_change_done"),
        ),
        name="password_change",
    ),

    path(
        "clave/hecho/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="accounts/password_change_done.html",
        ),
        name="password_change_done",
    ),

]
