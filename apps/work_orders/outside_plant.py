from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import FormView, ListView, TemplateView

from apps.organization.models import Branch, Zone
from apps.work_orders.models import OrderReason, WorkOrder
from apps.work_orders.services import create_outside_plant_order


class OutsidePlantCreateForm(forms.Form):
    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        label="Sede",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    zone = forms.ModelChoiceField(
        queryset=Zone.objects.filter(is_active=True).select_related("branch"),
        required=False,
        label="Zona",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    route = forms.CharField(
        label="Vía / tramo",
        min_length=3,
        max_length=220,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ej.: San Agustín de Cajas 3 - Jr. San Martín",
            }
        ),
    )
    reference = forms.CharField(
        label="Referencia",
        required=False,
        max_length=220,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    reason = forms.ModelChoiceField(
        queryset=OrderReason.objects.none(),
        label="Motivo",
        empty_label="Seleccione motivo...",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    detail = forms.CharField(
        label="Detalle",
        min_length=5,
        max_length=3000,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Describa la afectación o trabajo requerido...",
            }
        ),
    )
    priority = forms.ChoiceField(
        choices=WorkOrder.Priority.choices,
        initial=WorkOrder.Priority.NORMAL,
        label="Prioridad",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    scheduled_at = forms.DateTimeField(
        required=False,
        label="Fecha programada",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"class": "form-control", "type": "datetime-local"},
        ),
    )
    latitude = forms.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=7,
        label="Latitud",
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "0.0000001"}
        ),
    )
    longitude = forms.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=7,
        label="Longitud",
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "0.0000001"}
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["reason"].queryset = (
            OrderReason.objects
            .filter(
                order_type__code="OUTSIDE_PLANT",
                order_type__is_active=True,
                is_active=True,
            )
            .order_by("name")
        )

        if not self.is_bound and user is not None and user.branch_id:
            self.fields["branch"].initial = user.branch_id

    def clean(self):
        cleaned = super().clean()
        branch = cleaned.get("branch")
        zone = cleaned.get("zone")
        latitude = cleaned.get("latitude")
        longitude = cleaned.get("longitude")

        if zone and branch and zone.branch_id != branch.pk:
            self.add_error(
                "zone",
                "La zona seleccionada no pertenece a la sede indicada.",
            )

        if (latitude is None) != (longitude is None):
            raise forms.ValidationError(
                "Registre latitud y longitud juntas o deje ambas vacías."
            )

        return cleaned

    def service_arguments(self):
        return dict(self.cleaned_data)


class OutsidePlantQueueView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    ListView,
):
    permission_required = "work_orders.view_outsideplant"
    raise_exception = True
    model = WorkOrder
    template_name = "work_orders/outside_plant_queue.html"
    context_object_name = "orders"
    paginate_by = 30

    def get_queryset(self):
        return (
            WorkOrder.objects
            .filter(order_type__code="OUTSIDE_PLANT")
            .select_related(
                "branch",
                "zone",
                "reason",
                "created_by",
                "assigned_technician",
                "outside_plant_detail",
            )
            .annotate(participant_count=Count("participations__user", distinct=True))
            .order_by("-created_at", "-pk")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset = self.get_queryset()
        context["pending_count"] = queryset.filter(
            status=WorkOrder.Status.PENDING
        ).count()
        context["in_progress_count"] = queryset.filter(
            status=WorkOrder.Status.IN_PROGRESS
        ).count()
        context["can_create"] = self.request.user.has_perm(
            "work_orders.create_outsideplant"
        )
        return context


class OutsidePlantCreateView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    FormView,
):
    permission_required = "work_orders.create_outsideplant"
    raise_exception = True
    form_class = OutsidePlantCreateForm
    template_name = "work_orders/outside_plant_create.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        try:
            order = create_outside_plant_order(
                created_by=self.request.user,
                **form.service_arguments(),
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages)
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Orden PEX {order.order_number} registrada correctamente.",
        )
        return redirect(
            "work_orders:outside_plant_detail",
            pk=order.pk,
        )


class OutsidePlantDetailView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    TemplateView,
):
    permission_required = "work_orders.view_outsideplant"
    raise_exception = True
    template_name = "work_orders/outside_plant_detail.html"

    def get_order(self):
        if not hasattr(self, "_order"):
            self._order = get_object_or_404(
                WorkOrder.objects.select_related(
                    "branch",
                    "zone",
                    "reason",
                    "result",
                    "created_by",
                    "assigned_technician",
                    "outside_plant_detail",
                    "liquidation",
                ),
                pk=self.kwargs["pk"],
                order_type__code="OUTSIDE_PLANT",
            )
        return self._order

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.get_order()
        context.update({
            "order": order,
            "pex": order.outside_plant_detail,
            "participants": (
                order.participations
                .select_related("user")
                .order_by("started_at", "pk")
            ),
            "materials": (
                order.field_material_movements
                .select_related("material", "recorded_by")
                .order_by("movement_type", "material__name")
            ),
            "evidences": (
                order.evidences
                .select_related("uploaded_by")
                .order_by("-created_at")
            ),
        })
        return context
