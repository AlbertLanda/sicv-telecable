from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from apps.accounts.forms import ProfileContactForm


class ProfileView(LoginRequiredMixin, UpdateView):
    """
    Mi perfil: identidad de solo lectura + contacto editable.

    La vista siempre opera sobre el propio usuario autenticado
    (get_object() no admite pk de la URL): no hay parámetro que
    manipular para editar el perfil de otra persona.
    """

    form_class = ProfileContactForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Datos de contacto actualizados.")
        return super().form_valid(form)
