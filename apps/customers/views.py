from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.db.models import Q, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    FormView,
    UpdateView,
)

from .forms import (
    CustomerAddressForm,
    CustomerInitialForm,
    CustomerRegistrationForm,
)
from .models import Customer, CustomerAddress
from .services.sunat import consultar_documento, DocumentLookupError

from apps.organization.models import Zone
from apps.services.models import Subscription
from apps.contracts.models import Contract

# Solo se importa el modelo de solo-lectura OrderType para poblar los
# selectores de la maqueta visual de OT (ver CustomerWorkOrderUIPreviewView).
# No se importa apps.work_orders.services ni se crea ningún WorkOrder:
# la lógica de persistencia de órdenes queda fuera del alcance de esta
# actividad.
from apps.work_orders.models import OrderType, WorkOrder


class CustomerSearchView(LoginRequiredMixin, ListView):
    model = Customer
    template_name = "customers/search.html"
    context_object_name = "customers"
    paginate_by = 20

    def get_queryset(self):
        query = self.request.GET.get("q", "").strip()

        document_type = (
            self.request.GET.get("document_type", "")
            .strip()
            .upper()
        )

        document_number = (
            self.request.GET.get("document_number", "")
            .strip()
            .upper()
        )

        queryset = Customer.objects.filter(
            is_active=True
        )

        # ---------------------------------------------------------
        # BÚSQUEDA POR TIPO Y NÚMERO DE DOCUMENTO
        #
        # Se conserva por compatibilidad con el flujo anterior
        # y con las pruebas existentes.
        # ---------------------------------------------------------

        if document_type or document_number:

            if document_type:
                queryset = queryset.filter(
                    document_type=document_type
                )

            if document_number:
                queryset = queryset.filter(
                    document_number=document_number
                )

            return (
                queryset
                .select_related("branch")
                .distinct()
                .order_by(
                    "paternal_surname",
                    "maternal_surname",
                    "first_name",
                    "business_name",
                )
            )

        # ---------------------------------------------------------
        # BÚSQUEDA GENERAL POR PALABRAS
        #
        # Permite buscar por:
        # - Código de cliente
        # - DNI / RUC / CE / Pasaporte
        # - Nombres
        # - Apellido paterno
        # - Apellido materno
        # - Razón social
        # - Teléfono principal
        # - Teléfono secundario
        # - Dirección
        # - Distrito
        # - Referencia
        # - Número de medidor
        # ---------------------------------------------------------

        if not query:
            return Customer.objects.none()

        words = query.split()

        for word in words:
            word_filter = (
                Q(code__icontains=word)
                | Q(document_number__icontains=word)
                | Q(first_name__icontains=word)
                | Q(paternal_surname__icontains=word)
                | Q(maternal_surname__icontains=word)
                | Q(business_name__icontains=word)
                | Q(phone__icontains=word)
                | Q(secondary_phone__icontains=word)
                | Q(addresses__address__icontains=word)
                | Q(addresses__district__icontains=word)
                | Q(addresses__reference__icontains=word)
                | Q(addresses__meter_number__icontains=word)
            )

            queryset = queryset.filter(word_filter)

        return (
            queryset
            .select_related("branch")
            .distinct()
            .order_by(
                "paternal_surname",
                "maternal_surname",
                "first_name",
                "business_name",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        query = self.request.GET.get("q", "").strip()

        document_type = (
            self.request.GET.get("document_type", "")
            .strip()
            .upper()
        )

        document_number = (
            self.request.GET.get("document_number", "")
            .strip()
            .upper()
        )

        # ---------------------------------------------------------
        # CONTEXTO DE LA BÚSQUEDA GENERAL
        # ---------------------------------------------------------

        context["current_query"] = query
        context["customer_search"] = bool(
            query or document_type or document_number
        )

        # ---------------------------------------------------------
        # COMPATIBILIDAD CON EL FLUJO ANTERIOR
        # ---------------------------------------------------------

        context["current_document_type"] = document_type
        context["current_document_number"] = document_number
        context["document_types"] = Customer.DocumentType.choices

        # ---------------------------------------------------------
        # CLIENTE ENCONTRADO
        #
        # Se utiliza para compatibilidad con los tests y
        # con el flujo anterior de consulta por documento.
        # ---------------------------------------------------------

        customer_found = None

        if document_type or document_number:
            customers = context.get("customers")

            if customers is not None:
                customer_found = (
                    customers.first()
                    if customers.exists()
                    else None
                )

        context["customer_found"] = customer_found

        return context

class CustomerDocumentLookupView(LoginRequiredMixin, View):
    """
    Endpoint AJAX usado por el botón "Obtener datos" de la Pantalla 3
    (Registrar nuevo cliente).

    Consulta RENIEC (DNI) o SUNAT (RUC) según el tipo de documento
    seleccionado y devuelve un JSON con los datos encontrados para
    que el formulario los autocomplete en el navegador.

    Es de solo lectura: no crea, modifica ni guarda ningún Customer.
    Cualquier error (documento no encontrado, servicio no disponible,
    falla de red, etc.) se traduce a una respuesta JSON con
    "ok": false y un mensaje apto para mostrar directamente al
    usuario, para que el registro manual pueda continuar sin
    problemas aunque la consulta automática falle.
    """

    def get(self, request, *args, **kwargs):
        document_type = request.GET.get("document_type", "")
        document_number = request.GET.get("document_number", "")

        try:
            data = consultar_documento(document_type, document_number)
        except DocumentLookupError as exc:
            return JsonResponse(
                {"ok": False, "message": exc.message},
                status=exc.status_code,
            )

        return JsonResponse({"ok": True, "data": data})


class CustomerInitialCreateView(LoginRequiredMixin, FormView):
    """
    Pantalla 3.

    Solicita únicamente los datos mínimos necesarios
    para iniciar el registro del cliente.
    """

    form_class = CustomerInitialForm
    template_name = "customers/create_initial.html"

    def get_initial(self):
        initial = super().get_initial()

        initial["document_type"] = (
            self.request.GET.get(
                "document_type",
                "",
            )
            .strip()
            .upper()
        )

        initial["document_number"] = (
            self.request.GET.get(
                "document_number",
                "",
            )
            .strip()
            .upper()
        )

        return initial

    def form_valid(self, form):

        self.request.session["customer_registration"] = {
            "document_type": form.cleaned_data["document_type"],
            "document_number": form.cleaned_data["document_number"],
            "first_name": form.cleaned_data["first_name"],
            "paternal_surname": form.cleaned_data[
                "paternal_surname"
            ],
            "maternal_surname": form.cleaned_data[
                "maternal_surname"
            ],
            # Solo tiene valor para RUC (obtenido vía el botón
            # "Obtener datos" o ingresado manualmente). Se usa para
            # prellenar "Razón social" en la Pantalla 4.
            "business_name": form.cleaned_data.get(
                "business_name", ""
            ),
        }

        return redirect(
            "customers:general_create"
        )

class CustomerUseView(LoginRequiredMixin, DetailView):
    """
    Selecciona un cliente existente para utilizarlo
    en el siguiente flujo del sistema.
    """
    model = Customer

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        request.session["selected_customer_id"] = self.object.pk

        messages.success(
            request,
            f"Cliente seleccionado: {self.object}. Puedes continuar con las siguientes operaciones."
        )

        return redirect("customers:detail", pk=self.object.pk)


class CustomerGeneralDataView(LoginRequiredMixin, FormView):

    template_name = "customers/general_data.html"
    form_class = CustomerRegistrationForm

    def dispatch(self, request, *args, **kwargs):

        registration_data = request.session.get(
            "customer_registration"
        )

        if not registration_data:
            return redirect(
                "customers:search"
            )

        self.registration_data = registration_data

        return super().dispatch(
            request,
            *args,
            **kwargs,
        )

    def get_initial(self):

        initial = super().get_initial()

        initial.update(
            self.registration_data
        )

        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()

        kwargs["document_type"] = (
            self.registration_data["document_type"]
        )

        return kwargs

    def get_context_data(self, **kwargs):

        context = super().get_context_data(**kwargs)

        context["registration_data"] = (
            self.registration_data
        )

        context["person_type_display"] = dict(
            Customer.PersonType.choices
        ).get(
            Customer.person_type_for_document(
                self.registration_data["document_type"]
            )
        )

        return context

    def form_valid(self, form):

        try:

            with transaction.atomic():

                customer = form.save(
                    commit=False
                )

                # -----------------------------------------
                # DATOS DE PANTALLA 3
                # -----------------------------------------

                customer.document_type = (
                    self.registration_data[
                        "document_type"
                    ]
                )

                customer.document_number = (
                    self.registration_data[
                        "document_number"
                    ]
                )

                customer.first_name = (
                    self.registration_data[
                        "first_name"
                    ]
                )

                customer.paternal_surname = (
                    self.registration_data[
                        "paternal_surname"
                    ]
                )

                customer.maternal_surname = (
                    self.registration_data[
                        "maternal_surname"
                    ]
                )

                # -----------------------------------------
                # TIPO DE PERSONA
                # -----------------------------------------

                customer.person_type = (
                    Customer.person_type_for_document(
                        self.registration_data[
                            "document_type"
                        ]
                    )
                )

                # -----------------------------------------
                # CÓDIGO
                # -----------------------------------------

                customer.code = (
                    f"CLI-{uuid4().hex[:8].upper()}"
                )

                customer.save()

                self.object = customer

        except IntegrityError:

            form.add_error(
                None,
                (
                    "No fue posible registrar el cliente. "
                    "Verifique los datos e inténtelo nuevamente."
                ),
            )

            return self.form_invalid(form)

        # -----------------------------------------
        # CLIENTE SELECCIONADO
        # -----------------------------------------

        self.request.session[
            "selected_customer_id"
        ] = self.object.pk

        # -----------------------------------------
        # LIMPIAR DATOS TEMPORALES
        # -----------------------------------------

        self.request.session.pop(
            "customer_registration",
            None,
        )

        messages.success(
            self.request,
            (
                f"Cliente registrado correctamente. "
                f"Código de abonado: "
                f"{self.object.code}"
            ),
        )

        # -----------------------------------------
        # SIGUIENTE PASO
        # -----------------------------------------

        next_step = self.request.POST.get(
            "action",
            "finish",
        )

        # -----------------------------------------
        # NUEVA DIRECCIÓN
        # -----------------------------------------

        if next_step == "address":

            self.request.session[
                "customer_flow_return"
            ] = {
                "type": "general_data",
                "customer_pk": self.object.pk,
            }

            return redirect(
                "customers:address_create",
                customer_pk=self.object.pk,
            )

        # -----------------------------------------
        # NUEVA SUSCRIPCIÓN
        # -----------------------------------------

        if next_step == "subscription":

            self.request.session[
                "customer_flow_return"
            ] = {
                "type": "general_data",
                "customer_pk": self.object.pk,
            }

            return redirect(
                "services:subscription_create",
                customer_pk=self.object.pk,
            )

        # -----------------------------------------
        # NUEVO CONTRATO
        # -----------------------------------------

        if next_step == "contract":

            self.request.session[
                "customer_flow_return"
            ] = {
                "type": "general_data",
                "customer_pk": self.object.pk,
            }

            return redirect(
                "contracts:contract_create",
                customer_pk=self.object.pk,
            )

        # -----------------------------------------
        # FINAL NORMAL
        # -----------------------------------------

        return redirect(
            "customers:detail",
            pk=self.object.pk,
        )
    
class CustomerGeneralDataEditView(LoginRequiredMixin, UpdateView):
    model = Customer
    form_class = CustomerRegistrationForm
    template_name = "customers/general_data.html"
    context_object_name = "customer"

    def get_object(self, queryset=None):
        return get_object_or_404(
            Customer,
            pk=self.kwargs["customer_pk"],
            is_active=True,
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()

        kwargs["document_type"] = self.object.document_type

        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        customer = self.object

        context["customer"] = customer

        context["registration_data"] = {
            "document_type": customer.document_type,
            "document_number": customer.document_number,
            "first_name": customer.first_name,
            "paternal_surname": customer.paternal_surname,
            "maternal_surname": customer.maternal_surname,
        }

        context["person_type_display"] = dict(
            Customer.PersonType.choices
        ).get(customer.person_type)

        return context

    def form_valid(self, form):
        response = super().form_valid(form)

        messages.success(
            self.request,
            "Datos generales del cliente actualizados correctamente.",
        )

        return response

    def get_success_url(self):
        return reverse(
            "customers:detail",
            kwargs={"pk": self.object.pk},
        )

class CustomerDetailView(LoginRequiredMixin, DetailView):
    model = Customer
    template_name = "customers/detail.html"
    context_object_name = "customer"

    def get_queryset(self):
        address_queryset = (
            CustomerAddress.objects
            .select_related("zone")
            .order_by("-is_primary", "address")
        )

        work_order_queryset = (
            WorkOrder.objects
            .select_related(
                "order_type",
                "subtype",
                "reason",
                "cause",
                "result",
                "assigned_technician",
                "branch",
                "zone",
            )
            .order_by("-created_at")
        )

        subscription_queryset = (
            Subscription.objects
            .select_related("service_type", "plan", "address")
            .prefetch_related(
                Prefetch("work_orders", queryset=work_order_queryset),
                "contracts",
            )
            .order_by("-created_at")
        )

        contract_queryset = (
            Contract.objects
            .select_related(
                "subscription",
                "subscription__service_type",
                "subscription__plan",
            )
            .order_by("-created_at")
        )

        return (
            Customer.objects
            .select_related("branch")
            .prefetch_related(
                Prefetch("addresses", queryset=address_queryset),
                Prefetch("subscriptions", queryset=subscription_queryset),
                Prefetch("contracts", queryset=contract_queryset),
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer = self.object

        context["addresses"] = customer.addresses.all()
        context["subscriptions"] = customer.subscriptions.all()
        context["contracts"] = customer.contracts.all()

        context["work_orders"] = (
            WorkOrder.objects
            .filter(subscription__customer=customer)
            .select_related(
                "subscription",
                "order_type",
                "subtype",
                "reason",
                "cause",
                "result",
                "branch",
                "zone",
                "assigned_technician",
            )
            .order_by("-created_at")
        )

        context["selected_customer"] = (
            self.request.session.get("selected_customer_id") == customer.pk
        )

        return context


class CustomerWorkOrderUIPreviewView(LoginRequiredMixin, DetailView):
    """
    Propuesta visual del futuro formulario de creación de órdenes
    de trabajo (ver actividad "Ajuste funcional y visual del
    registro de clientes y preparación de UI para órdenes").

    Esta vista es SOLO de lectura / presentación:
    - No define ningún método POST.
    - No importa ni utiliza apps.work_orders.services.
    - No crea ni guarda ninguna instancia de WorkOrder.

    Los catálogos de OrderType / OrderSubtype / OrderReason se leen
    únicamente para poblar los selectores de la maqueta (misma
    lógica de solo lectura que ya usa la ficha del cliente para
    mostrar las órdenes existentes). La lógica de negocio real para
    crear órdenes será proporcionada por el servicio backend
    implementado en otra actividad.
    """

    model = Customer
    template_name = "customers/work_order_ui_preview.html"
    context_object_name = "customer"

    def get_queryset(self):
        return Customer.objects.select_related("branch")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        customer = self.object

        context["subscriptions"] = (
            Subscription.objects
            .filter(customer=customer)
            .select_related("service_type", "plan", "address")
            .order_by("-created_at")
        )

        context["order_types"] = (
            OrderType.objects
            .filter(is_active=True)
            .prefetch_related("subtypes", "reasons")
            .order_by("name")
        )

        context["zones"] = (
            Zone.objects
            .filter(branch=customer.branch, is_active=True)
            .order_by("name")
        )

        return context


class CustomerAddressCreateView(LoginRequiredMixin, CreateView):
    model = CustomerAddress
    form_class = CustomerAddressForm
    template_name = "customers/address_create.html"

    def dispatch(self, request, *args, **kwargs):
        self.customer = get_object_or_404(
            Customer,
            pk=self.kwargs["customer_pk"],
            is_active=True,
        )

        return super().dispatch(
            request,
            *args,
            **kwargs,
        )

    def form_valid(self, form):
        try:
            with transaction.atomic():
                address = form.save(commit=False)
                address.customer = self.customer

                if address.is_primary:
                    CustomerAddress.objects.filter(
                        customer=self.customer,
                        is_primary=True,
                    ).update(is_primary=False)

                address.save()
                self.object = address

        except IntegrityError:
            form.add_error(
                None,
                (
                    "No fue posible registrar la dirección. "
                    "Verifique los datos e inténtelo nuevamente."
                ),
            )
            return self.form_invalid(form)

        messages.success(
            self.request,
            "Dirección registrada correctamente.",
        )

        return redirect(
            "customers:detail",
            pk=self.customer.pk,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["customer"] = self.customer

        context["return_to_general"] = (
            self.request.session.get("customer_flow_return", {}).get("type")
            == "general_data"
        )

        return context