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
from apps.audit.models import AuditEvent
from apps.organization.context_processors import get_active_branch


class ProfileView(LoginRequiredMixin, UpdateView):
    """Perfil editable del usuario autenticado con auditoría de cambios."""

    form_class = ProfileContactForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")
    audited_fields = (
        ("username", "Usuario"),
        ("first_name", "Nombres"),
        ("last_name", "Apellidos"),
        ("phone", "Teléfono"),
        ("email", "Correo"),
    )

    def dispatch(self, request, *args, **kwargs):
        # LoginRequiredMixin debe poder redirigir a un usuario anónimo antes
        # de que intentemos leer atributos propios del modelo User.
        self.profile_before = {}
        if request.user.is_authenticated:
            self.profile_before = {
                field: getattr(request.user, field)
                for field, _label in self.audited_fields
            }
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        changes = {}
        for field, label in self.audited_fields:
            before = self.profile_before.get(field) or ""
            after = form.cleaned_data.get(field) or ""
            if before != after:
                changes[label] = {
                    "before": before or "—",
                    "after": after or "—",
                }

        response = super().form_valid(form)

        if changes:
            AuditEvent.objects.create(
                actor=self.request.user,
                branch=get_active_branch(self.request),
                method=self.request.method,
                route_name="accounts:profile",
                path=self.request.path,
                status_code=response.status_code,
                description="Actualizó su perfil",
                changes=changes,
            )
            messages.success(
                self.request,
                "Perfil actualizado. Los cambios quedaron registrados.",
            )
        else:
            messages.info(self.request, "No se detectaron cambios en el perfil.")

        return response


class PersonnelListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Directorio operativo de personal para Administración."""

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

        # Un administrador operativo administra personal común. Las cuentas
        # de administrador y superusuario quedan reservadas al superusuario,
        # que representa la capa administrativa con permisos ampliados.
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
