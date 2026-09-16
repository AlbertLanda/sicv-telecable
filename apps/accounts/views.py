from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from apps.accounts.forms import (
    PersonnelCreateForm,
    PersonnelForm,
    ProfileContactForm,
)
from apps.accounts.models import User


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


class PersonnelListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Directorio operativo de personal para Contabilidad y Administración."""

    model = User
    template_name = "accounts/personnel_list.html"
    context_object_name = "personnel"
    permission_required = "accounts.view_user"
    paginate_by = 30

    def get_queryset(self):
        queryset = User.objects.select_related("branch", "office").order_by(
            "first_name", "last_name", "username"
        )
        query = self.request.GET.get("q", "").strip()
        role = self.request.GET.get("role", "").strip()

        if query:
            queryset = queryset.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(email__icontains=query)
            )

        if role in User.Role.values:
            queryset = queryset.filter(role=role)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "").strip()
        context["current_role"] = self.request.GET.get("role", "").strip()
        context["role_choices"] = User.Role.choices
        context["can_create"] = self.request.user.has_perm("accounts.add_user")
        context["can_edit"] = self.request.user.has_perm("accounts.change_user")
        return context


class PersonnelCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = User
    form_class = PersonnelCreateForm
    template_name = "accounts/personnel_form.html"
    permission_required = "accounts.add_user"
    success_url = reverse_lazy("accounts:personnel_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Personal creado correctamente.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_title"] = "Nuevo personal"
        context["submit_label"] = "Crear personal"
        return context


class PersonnelUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = User
    form_class = PersonnelForm
    template_name = "accounts/personnel_form.html"
    permission_required = "accounts.change_user"
    success_url = reverse_lazy("accounts:personnel_list")

    def get_object(self, queryset=None):
        user = super().get_object(queryset=queryset)

        # Contabilidad administra personal operativo. Las cuentas técnicas de
        # superusuario/administrador quedan reservadas a otro superusuario.
        if (
            not self.request.user.is_superuser
            and (user.is_superuser or user.role == User.Role.ADMIN)
        ):
            raise PermissionDenied("Esta cuenta solo puede ser administrada por un superusuario.")

        return user

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Datos del personal actualizados.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_title"] = "Editar personal"
        context["submit_label"] = "Guardar cambios"
        return context
