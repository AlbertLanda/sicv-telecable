from datetime import date, timedelta

from django import forms
from django.db import models

from apps.accounts.models import User
from apps.services.models import Subscription
from apps.work_orders.models import (
    OrderReason,
    OrderType,
    WorkOrder,
    WorkOrderEvidence,
    WorkOrderFieldSheet,
)


class SubscriptionChoiceField(forms.ModelChoiceField):
    """
    Suscripciones sin el nombre del abonado.

    `Subscription.__str__` antepone el cliente, útil donde la suscripción
    aparece suelta. Aquí no: el alta ocurre dentro de la ficha de ese
    cliente, así que repetir su nombre en cada opción solo desplaza fuera
    de la vista lo que sí distingue una suscripción de otra.
    """

    def label_from_instance(self, obj):
        return str(obj.plan)


class ReasonChoiceField(forms.ModelChoiceField):
    """
    Motivos sin el servicio delante.

    `OrderReason.__str__` antepone el tipo de orden, necesario donde un
    motivo aparece suelto —dos servicios pueden tener un «SIN SEÑAL»—.
    Aquí no: el selector ya está filtrado por el servicio elegido justo
    encima, así que el prefijo se repite en cada opción y empuja fuera de
    la vista la única parte que las distingue.
    """

    def label_from_instance(self, obj):
        return obj.name


class WorkOrderCreateForm(forms.ModelForm):
    subscription = SubscriptionChoiceField(
        queryset=Subscription.objects.none(),
        label="Suscripción",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    reason = ReasonChoiceField(
        queryset=OrderReason.objects.none(),
        required=False,
        label="Motivo",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

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
            "reason",
            "attention_type",
            "priority",
            "scheduled_at",
            "detail",
        ]

        widgets = {
            "order_type": forms.Select(
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
            "order_type": "Servicio",
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

        # La sede y la zona no se piden: el dominio las deriva del cliente
        # y de la dirección de la suscripción, y rechaza cualquier otra.
        # Pedirlas solo ofrecía al operador una elección que no existía.

        if customer is None:
            self.fields["subscription"].queryset = (
                Subscription.objects.none()
            )

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

        # ---------------------------------------------------------
        # CATÁLOGOS ACTIVOS
        #
        # Un catálogo inactivo no se ofrece ni se acepta. La coherencia
        # entre servicio y motivo la valida el dominio.
        # ---------------------------------------------------------

        # El catálogo se acota a lo emitible sobre los servicios que el
        # cliente realmente tiene. Ofrecer "AVERÍA CABLE" a un abonado
        # solo-internet no es una opción: es una orden imposible que
        # alguien acabaría creando.
        order_types = OrderType.objects.filter(is_active=True)

        if customer is not None:
            service_type_ids = list(
                self.fields["subscription"].queryset
                .values_list("service_type_id", flat=True)
                .distinct()
            )

            order_types = order_types.filter(
                models.Q(service_types__isnull=True)
                | models.Q(service_types__in=service_type_ids)
            ).distinct()

        self.fields["order_type"].queryset = order_types.order_by("name")

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
            "Seleccione el servicio..."
        )

        self.fields["reason"].empty_label = "Sin motivo"

        self.fields["order_type"].help_text = (
            "Las opciones dependen del servicio de la suscripción elegida."
        )

        self.fields["reason"].help_text = (
            "Las opciones dependen del servicio elegido."
        )
        self.fields["reason"].required = False

    def clean(self):
        cleaned_data = super().clean()

        subscription = cleaned_data.get("subscription")
        order_type = cleaned_data.get("order_type")

        # -------------------------------------------------------------
        # COHERENCIA SERVICIO <-> SUSCRIPCIÓN
        #
        # El encadenado del formulario ya evita elegir un servicio que no
        # corresponde, pero el navegador no es la última palabra: un POST
        # armado a mano llegaría igual. La regla se vuelve a comprobar
        # aquí, donde sí es vinculante.
        # -------------------------------------------------------------

        if (
            subscription is not None
            and order_type is not None
            and not order_type.applies_to_service_type(
                subscription.service_type_id
            )
        ):
            self.add_error(
                "order_type",
                (
                    f"«{order_type.name}» no se emite sobre una suscripción "
                    f"{subscription.service_type}."
                ),
            )

        return cleaned_data

    def cascade_data(self):
        """
        Mapa que el formulario usa para encadenar los selectores.

        Se resuelve en el servidor y viaja como JSON: encadenar pidiendo
        el catálogo por AJAX en cada cambio añadiría latencia y un
        endpoint más que autorizar, para datos que ya están cargados.
        """

        subscriptions = {
            str(subscription.pk): {
                "serviceType": subscription.service_type_id,
                "serviceCode": subscription.service_type.code,
            }
            for subscription in self.fields["subscription"].queryset
        }

        order_types = {
            str(order_type.pk): {
                "name": order_type.name,
                # Lista vacía = transversal, se ofrece sobre cualquier
                # servicio.
                "serviceTypes": [
                    service_type.pk
                    for service_type in order_type.service_types.all()
                ],
            }
            for order_type in (
                self.fields["order_type"].queryset
                .prefetch_related("service_types")
            )
        }

        return {
            "subscriptions": subscriptions,
            "orderTypes": order_types,
            "reasons": {
                str(reason.pk): reason.order_type_id
                for reason in self.fields["reason"].queryset
            },
        }

    def service_arguments(self):
        data = self.cleaned_data

        return {
            "subscription": data["subscription"],
            "order_type": data["order_type"],
            "customer": self.customer,
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


def validate_scheduling_date(value):
    # Dejar margen para navegar una semana y convertir entre UTC y Lima sin
    # desbordar datetime en los extremos de los años 1 y 9999.
    if not date.min + timedelta(days=14) <= value <= date.max - timedelta(days=14):
        raise forms.ValidationError("La fecha está fuera del intervalo admitido.")


class WorkOrderScheduleWeekForm(forms.Form):
    fecha = forms.DateField(required=False, validators=[validate_scheduling_date])


class WorkOrderRescheduleForm(forms.Form):
    date = forms.DateField(
        validators=[validate_scheduling_date],
        error_messages={
            "required": "Debe indicar la nueva fecha.",
            "invalid": "Debe indicar una fecha válida.",
        },
    )
    reason = forms.CharField(required=False)
