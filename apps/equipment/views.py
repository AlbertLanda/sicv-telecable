from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import TemplateView

from apps.customers.models import Customer
from apps.organization.context_processors import get_active_branch

from .forms import AssignmentForm, EquipmentCreateForm, EquipmentFilterForm, RemovalForm, ReviewForm
from .models import Equipment, EquipmentAssignment, normalize_mac
from .services import assign_equipment, register_equipment, remove_equipment, review_equipment


class EquipmentAccessMixin(LoginRequiredMixin, PermissionRequiredMixin):
    permission_required = "equipment.view_equipment"

    def branch(self):
        return get_active_branch(self.request)

    def equipment(self):
        return get_object_or_404(Equipment, pk=self.kwargs["pk"], branch=self.branch())

    def customer(self):
        return get_object_or_404(Customer, pk=self.kwargs["customer_pk"], branch=self.branch())

    def render_to_response(self, context, **kwargs):
        response = super().render_to_response(context, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response


class EquipmentListView(EquipmentAccessMixin, TemplateView):
    template_name = "equipment/list.html"

    def get(self, request, *args, **kwargs):
        branch = self.branch()
        form = EquipmentFilterForm(request.GET)
        valid = form.is_valid()
        if branch is None:
            form.add_error(None, "Selecciona una sede activa en la barra superior.")
            valid = False
        context = self.get_context_data(form=form, branch=branch)
        if valid:
            rows = Equipment.objects.filter(branch=branch)
            q = form.cleaned_data["q"]
            if q:
                search = Q(serial_number__icontains=q) | Q(mac_address__icontains=q) | Q(brand__icontains=q) | Q(model__icontains=q)
                try:
                    search |= Q(mac_address=normalize_mac(q))
                except ValidationError:
                    pass
                rows = rows.filter(search)
            if form.cleaned_data["status"]:
                rows = rows.filter(status=form.cleaned_data["status"])
            context["page_obj"] = Paginator(rows, 25).get_page(request.GET.get("page"))
            context["page_query"] = urlencode(form.cleaned_data)
        return self.render_to_response(context, status=200 if valid else 400)


class EquipmentDetailView(EquipmentAccessMixin, TemplateView):
    template_name = "equipment/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        equipment = self.equipment()
        rows = equipment.assignments.select_related("subscription__customer", "assigned_by", "removed_by", "work_order")
        context.update(equipment=equipment, page_obj=Paginator(rows, 25).get_page(self.request.GET.get("page")))
        context["review_page"] = Paginator(equipment.reviews.select_related("reviewed_by"), 10).get_page(self.request.GET.get("reviews"))
        return context


class CustomerEquipmentView(EquipmentAccessMixin, TemplateView):
    template_name = "equipment/customer.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer = self.customer()
        rows = EquipmentAssignment.objects.filter(subscription__customer=customer, equipment__branch=self.branch()).select_related(
            "equipment", "subscription", "assigned_by", "removed_by", "work_order",
        )
        context.update(customer=customer, page_obj=Paginator(rows, 25).get_page(self.request.GET.get("page")))
        return context


class EquipmentFormView(EquipmentAccessMixin, TemplateView):
    template_name = "equipment/form.html"

    def get(self, request, *args, **kwargs):
        return self.show_form(self.form())

    def post(self, request, *args, **kwargs):
        form = self.form(request.POST)
        if form.is_valid():
            try:
                result = self.save(form.cleaned_data)
            except ValidationError as error:
                form.add_error(None, "; ".join(error.messages))
            else:
                messages.success(request, self.success_message)
                return redirect(self.success_url(result))
        return self.show_form(form, status=400)

    def show_form(self, form, status=200):
        return self.render_to_response(self.get_context_data(form=form, **self.form_context()), status=status)


class EquipmentCreateView(EquipmentFormView):
    permission_required = ("equipment.view_equipment", "equipment.add_equipment")
    success_message = "Equipo registrado. Ya puedes asignarlo desde la ficha del abonado."

    def form(self, data=None):
        return EquipmentCreateForm(data)

    def form_context(self):
        return {"title": "Registrar equipo", "description": "El equipo se registrará en la sede activa. Comprueba la etiqueta del fabricante.", "cancel_url": reverse("equipment:list"), "submit_label": "Registrar equipo"}

    def save(self, fields):
        return register_equipment(branch=self.branch(), user=self.request.user, **fields)

    def success_url(self, result):
        return reverse("equipment:detail", args=[result.pk])


class EquipmentAssignView(EquipmentFormView):
    permission_required = ("equipment.view_equipment", "equipment.assign_equipment")
    success_message = "Asignación registrada. Consulta su estado y el historial en la ficha."

    def form(self, data=None):
        return AssignmentForm(data, customer=self.customer(), branch=self.branch(), user=self.request.user)

    def form_context(self):
        customer = self.customer()
        return {"title": "Asignar equipo", "description": f"Abonado: {customer.code} · {customer}", "cancel_url": reverse("equipment:customer", args=[customer.pk]), "submit_label": "Confirmar asignación"}

    def save(self, fields):
        return assign_equipment(branch=self.branch(), user=self.request.user, **fields)

    def success_url(self, result):
        return reverse("equipment:customer", args=[self.kwargs["customer_pk"]])


class EquipmentRemoveView(EquipmentFormView):
    permission_required = ("equipment.view_equipment", "equipment.assign_equipment")
    success_message = "Retiro registrado. El historial del equipo se conserva."

    def assignment(self):
        return get_object_or_404(
            EquipmentAssignment.objects.select_related("equipment", "subscription__customer"),
            pk=self.kwargs["assignment_pk"], equipment__branch=self.branch(),
        )

    def form(self, data=None):
        self.assignment()  # Exige alcance también antes de procesar un POST.
        return RemovalForm(data)

    def form_context(self):
        assignment = self.assignment()
        return {"title": "Registrar retiro de equipo", "description": f"{assignment.equipment} · Servicio {assignment.service_code_snapshot}", "cancel_url": reverse("equipment:detail", args=[assignment.equipment_id]), "submit_label": "Confirmar retiro"}

    def save(self, fields):
        return remove_equipment(assignment=self.assignment(), branch=self.branch(), user=self.request.user, **fields)

    def success_url(self, result):
        return reverse("equipment:detail", args=[result.equipment_id])


class EquipmentReviewView(EquipmentFormView):
    permission_required = ("equipment.view_equipment", "equipment.change_equipment")
    success_message = "Revisión registrada y estado del equipo actualizado."

    def form(self, data=None):
        self.equipment()
        return ReviewForm(data)

    def form_context(self):
        equipment = self.equipment()
        return {"title": "Revisar estado del equipo", "description": str(equipment), "cancel_url": reverse("equipment:detail", args=[equipment.pk]), "submit_label": "Guardar revisión"}

    def save(self, fields):
        return review_equipment(equipment=self.equipment(), branch=self.branch(), user=self.request.user, **fields)

    def success_url(self, result):
        return reverse("equipment:detail", args=[result.pk])
