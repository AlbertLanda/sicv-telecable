from django import forms
from django.db.models import Q

from apps.accounts.models import User
from apps.organization.models import Branch, Zone
from apps.services.models import Subscription
from apps.work_orders.models import (
    OrderReason,
    OrderSubtype,
    OrderType,
    WorkOrder,
    WorkOrderEvidence,
    WorkOrderFieldSheet,
)


class WorkOrderCreateForm(forms.ModelForm):
    scheduled_at = forms.DateTimeField(
        required=False,
        label="Fecha programada",
        input_formats=[
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
        ],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "class": "form-control",
                "type": "datetime-local",
            },
        ),
        help_text="Opcional. Fecha prevista de atención.",
    )

    class Meta:
        model = WorkOrder

        fields = [
            "subscription",
            "order_type",
            "subtype",
            "reason",
            "branch",
            "zone",
            "attention_type",
            "priority",
            "scheduled_at",
            "detail",
        ]

        widgets = {
            "subscription": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "order_type": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "subtype": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "reason": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "branch": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "zone": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "attention_type": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "priority": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "detail": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": (
                        "Observaciones operativas para el técnico..."
                    ),
                }
            ),
        }

        labels = {
            "subscription": "Suscripción",
            "order_type": "Tipo de orden",
            "subtype": "Subtipo",
            "reason": "Motivo",
            "branch": "Sede",
            "zone": "Zona",
            "attention_type": "Tipo de atención",
            "priority": "Prioridad",
            "detail": "Detalle de la solicitud",
        }

    def __init__(self, *args, **kwargs):
        customer = kwargs.pop("customer", None)

        super().__init__(*args, **kwargs)

        self.customer = customer

        # ---------------------------------------------------------
        # ÁMBITO DEL CLIENTE
        #
        # Sin cliente resuelto no hay nada que ofrecer: se prefiere un
        # formulario vacío antes que uno que muestre datos de terceros.
        # ---------------------------------------------------------

        if customer is None:
            self.fields["subscription"].queryset = (
                Subscription.objects.none()
            )

            self.fields["branch"].queryset = Branch.objects.none()
            self.fields["zone"].queryset = Zone.objects.none()

        else:
            # Solo las suscripciones del cliente mostrado. Una suscripción
            # de otro cliente enviada por POST no está en este queryset.
            self.fields["subscription"].queryset = (
                Subscription.objects
                .filter(
                    customer=customer,
                    is_active=True,
                )
                .select_related("service_type", "plan", "address")
                .order_by("-created_at")
            )

            # La sede de la orden es siempre la del cliente: se muestra para
            # que el operador la vea, pero no es una elección abierta.
            self.fields["branch"].queryset = (
                Branch.objects.filter(pk=customer.branch_id)
            )

            self.fields["branch"].initial = customer.branch_id
            self.fields["branch"].empty_label = None

            # Solo zonas activas de esa sede: una zona de otra sede no es
            # una opción válida del formulario.
            self.fields["zone"].queryset = (
                Zone.objects
                .filter(
                    branch=customer.branch_id,
                    is_active=True,
                )
                .order_by("name")
            )

        # ---------------------------------------------------------
        # CATÁLOGOS ACTIVOS
        #
        # Un catálogo inactivo no se ofrece ni se acepta. La coherencia
        # entre tipo, subtipo y motivo la valida el dominio.
        # ---------------------------------------------------------

        self.fields["order_type"].queryset = (
            OrderType.objects
            .filter(is_active=True)
            .order_by("name")
        )

        self.fields["subtype"].queryset = (
            OrderSubtype.objects
            .filter(is_active=True)
            .select_related("order_type")
            .order_by("order_type__name", "name")
        )

        self.fields["reason"].queryset = (
            OrderReason.objects
            .filter(is_active=True)
            .select_related("order_type")
            .order_by("order_type__name", "name")
        )

        # ---------------------------------------------------------
        # PRESENTACIÓN DE LOS SELECTORES
        # ---------------------------------------------------------

        self.fields["subscription"].empty_label = (
            "Seleccione una suscripción del cliente..."
        )

        self.fields["order_type"].empty_label = (
            "Seleccione el tipo de orden..."
        )

        self.fields["subtype"].empty_label = "Sin subtipo"
        self.fields["reason"].empty_label = "Sin motivo"
        self.fields["zone"].empty_label = "Zona de la dirección del servicio"

        self.fields["subtype"].required = False
        self.fields["reason"].required = False
        self.fields["zone"].required = False

        self.fields["zone"].help_text = (
            "Opcional. Si se deja vacía se usa la zona de la dirección "
            "de la suscripción."
        )

    def service_arguments(self):
        data = self.cleaned_data

        return {
            "subscription": data["subscription"],
            "order_type": data["order_type"],
            "customer": self.customer,
            "branch": data.get("branch"),
            "zone": data.get("zone"),
            "subtype": data.get("subtype"),
            "reason": data.get("reason"),
            "attention_type": data.get("attention_type"),
            "priority": data.get("priority"),
            "detail": data.get("detail", ""),
            "scheduled_at": data.get("scheduled_at"),
        }


class WorkOrderAssignForm(forms.Form):

    assigned_technician = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="Técnico asignado",
        empty_label="Seleccione un técnico...",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
        error_messages={
            "invalid_choice": (
                "El técnico seleccionado no es elegible para esta orden."
            ),
        },
    )

    remarks = forms.CharField(
        required=False,
        label="Observación de la asignación",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": (
                    "Indicaciones para el despacho (opcional)..."
                ),
            }
        ),
        help_text=(
            "Opcional. Queda registrada en el historial de asignaciones."
        ),
    )

    def __init__(self, *args, **kwargs):
        order = kwargs.pop("order", None)

        super().__init__(*args, **kwargs)

        self.order = order

        if order is None:
            return

        self.fields["assigned_technician"].queryset = (
            User.objects
            .filter(
                role=User.Role.TECHNICIAN,
                is_active=True,
            )
            .select_related("branch")
            .order_by(
                "branch__name",
                "first_name",
                "last_name",
                "username",
            )
        )


class WorkOrderStartAttentionForm(forms.Form):
    """
    Confirmación del inicio de atención de una orden ya despachada.

    Decisiones deliberadas:

    - Es un forms.Form y no un ModelForm: no describe la orden ni la edita.
      Solo transporta la observación con la que el operador confirma.
    - Tiene un único campo, y es opcional. El estado destino, la hora real de
      inicio y el técnico responsable NO son campos del formulario: los pone
      el dominio. Al no existir, ningún POST manipulado puede influir en la
      transición, ni siquiera enviando esos nombres a mano.
    - La misma forma -una observación y nada más- es la que deberá aceptar la
      futura API del técnico: el contrato de entrada del inicio de atención se
      define aquí una sola vez.
    """

    remarks = forms.CharField(
        required=False,
        label="Observación del inicio",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": (
                    "Observación breve del inicio de atención (opcional)..."
                ),
            }
        ),
        help_text=(
            "Opcional. Queda registrada en el historial de estados de la orden."
        ),
    )


class WorkOrderFieldSheetForm(forms.ModelForm):
    """
    Datos técnicos de campo que completa el técnico en la ficha de la orden.

    Es un ModelForm de WorkOrderFieldSheet, pero quien persiste no es
    form.save(): la vista pasa cleaned_data a services.update_field_sheet(),
    que es el único camino autorizado a escribir el modelo. Aquí solo se
    valida forma y presentación (widgets, mensajes en español), no identidad
    del técnico ni estado de la orden -eso lo decide el servicio-.
    """

    class Meta:
        model = WorkOrderFieldSheet

        fields = [
            "nap",
            "terminal",
            "equipment_code",
            "seal_number",
            "notes",
        ]

        widgets = {
            "nap": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ej: NAP-014",
                    "inputmode": "text",
                }
            ),
            "terminal": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ej: 5",
                    "inputmode": "text",
                }
            ),
            "equipment_code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ej: AA:BB:CC:DD:EE:FF o serie del equipo",
                }
            ),
            "seal_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ej: PRC-000123",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Observaciones de la visita en campo...",
                }
            ),
        }

        labels = {
            "nap": "NAP",
            "terminal": "Borne",
            "equipment_code": "MAC / Equipo",
            "seal_number": "Precinto",
            "notes": "Observaciones",
        }


class WorkOrderEvidenceUploadForm(forms.ModelForm):
    """
    Adjunto de una evidencia (foto o archivo) a la orden.

    Igual que WorkOrderFieldSheetForm: valida forma, no autorización. La
    vista delega la creación en services.add_work_order_evidence(), que es
    quien decide si el técnico puede adjuntar sobre esta orden.
    """

    class Meta:
        model = WorkOrderEvidence

        fields = [
            "file",
            "description",
        ]

        widgets = {
            "file": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    # `capture` sugiere la cámara del dispositivo en móviles
                    # compatibles; en escritorio el navegador simplemente lo
                    # ignora y abre el selector de archivos habitual.
                    "capture": "environment",
                    "accept": "image/*,application/pdf",
                }
            ),
            "description": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Descripción breve (opcional)...",
                }
            ),
        }

        labels = {
            "file": "Archivo o fotografía",
            "description": "Descripción",
        }
