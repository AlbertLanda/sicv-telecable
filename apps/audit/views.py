from datetime import date

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q
from django.views.generic import ListView

from apps.accounts.models import User
from apps.organization.context_processors import get_active_branch

from .models import AuditEvent


class ActivityListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Actividad reciente del personal en la sede activa."""

    model = AuditEvent
    template_name = "audit/activity_list.html"
    context_object_name = "events"
    permission_required = "audit.view_auditevent"
    paginate_by = 50

    def get_queryset(self):
        queryset = AuditEvent.objects.select_related(
            "actor",
            "branch",
        ).order_by("-created_at", "-pk")

        branch = get_active_branch(self.request)
        if branch is not None:
            queryset = queryset.filter(branch=branch)

        actor = (self.request.GET.get("actor") or "").strip()
        if actor.isdigit():
            queryset = queryset.filter(actor_id=int(actor))

        raw_day = (self.request.GET.get("day") or "").strip()
        if raw_day:
            try:
                queryset = queryset.filter(created_at__date=date.fromisoformat(raw_day))
            except ValueError:
                pass

        query = (self.request.GET.get("q") or "").strip()
        if query:
            queryset = queryset.filter(
                Q(actor__username__icontains=query)
                | Q(actor__first_name__icontains=query)
                | Q(actor__last_name__icontains=query)
                | Q(description__icontains=query)
                | Q(route_name__icontains=query)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        branch = get_active_branch(self.request)
        users = User.objects.filter(is_active=True).order_by(
            "first_name",
            "last_name",
            "username",
        )
        if branch is not None:
            users = users.filter(branch=branch)

        context.update(
            {
                "branch": branch,
                "users": users,
                "query": (self.request.GET.get("q") or "").strip(),
                "current_actor": (self.request.GET.get("actor") or "").strip(),
                "selected_day": (self.request.GET.get("day") or "").strip(),
            }
        )
        return context
