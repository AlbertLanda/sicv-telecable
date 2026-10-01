from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import DetailView, FormView, ListView, View

from apps.customers.models import Customer
from apps.organization.context_processors import get_active_branch
from apps.payments.models import Issuer
from .forms import DraftForm, FiscalProfileForm
from .models import FiscalDocument, FiscalProfile
from .services import cancel_draft, prepare_draft, save_profile


class DraftListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "fiscal.view_fiscaldocument"
    model = FiscalDocument
    template_name = "fiscal/list.html"
    context_object_name = "documents"
    paginate_by = 30

    def get_queryset(self):
        return FiscalDocument.objects.filter(branch=get_active_branch(self.request)).select_related("created_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # La búsqueda exacta evita cargar el padrón completo en un selector.
        code = self.request.GET.get("customer_code", "").strip()
        context["customer_code"] = code
        if code and self.request.user.has_perm("fiscal.add_fiscaldocument"):
            context["selected_customer"] = Customer.objects.filter(
                branch=get_active_branch(self.request), code=code,
            ).first()
        context["issuers"] = Issuer.objects.filter(is_active=True)
        return context


class DraftCreateView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    permission_required = ("fiscal.add_fiscaldocument", "fiscal.view_fiscaldocument")
    template_name = "fiscal/create.html"
    form_class = DraftForm

    def get_customer(self):
        if not hasattr(self, "customer"):
            self.customer = get_object_or_404(
                Customer, pk=self.kwargs["customer_id"], branch=get_active_branch(self.request),
            )
        return self.customer

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "customer": self.get_customer()}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "customer": self.get_customer()}

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            document = prepare_draft(
                actor=self.request.user, branch=get_active_branch(self.request),
                customer_id=self.get_customer().pk, issuer_id=data["issuer"].pk,
                document_type=data["document_type"], charge_ids=[c.pk for c in data["charges"]],
                proposed_issue_date=data["proposed_issue_date"], request_key=data["request_key"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        return redirect("fiscal:detail", public_id=document.public_id)


class DraftDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    permission_required = "fiscal.view_fiscaldocument"
    model = FiscalDocument
    template_name = "fiscal/detail.html"
    context_object_name = "document"
    slug_field = "public_id"
    slug_url_kwarg = "public_id"

    def get_queryset(self):
        return FiscalDocument.objects.filter(branch=get_active_branch(self.request)).prefetch_related("events__actor")


class DraftCancelView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = ("fiscal.cancel_fiscaldocument", "fiscal.view_fiscaldocument")

    def post(self, request, public_id):
        document = get_object_or_404(FiscalDocument, public_id=public_id, branch=get_active_branch(request))
        try:
            cancel_draft(document_id=document.pk, actor=request.user,
                         branch=get_active_branch(request), reason=request.POST.get("reason"))
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect("fiscal:detail", public_id=public_id)


class ProfileView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    # Preparar el primer perfil y modificarlo exige ambos permisos. No se
    # conceden por rol hasta cerrar la matriz de Contabilidad.
    permission_required = ("fiscal.add_fiscalprofile", "fiscal.change_fiscalprofile")
    template_name = "fiscal/profile.html"
    form_class = FiscalProfileForm

    def get_form_kwargs(self):
        self.issuer = get_object_or_404(Issuer, pk=self.kwargs["issuer_id"], is_active=True)
        profile = FiscalProfile.objects.filter(issuer=self.issuer).first() or FiscalProfile(issuer=self.issuer)
        return {**super().get_form_kwargs(), "instance": profile}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["issuer"] = self.issuer
        return context

    def form_valid(self, form):
        try:
            save_profile(actor=self.request.user, issuer_id=self.issuer.pk, values=form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, "Configuración guardada. La emisión real continúa bloqueada.")
        return redirect(reverse("fiscal:profile", kwargs={"issuer_id": self.issuer.pk}))
