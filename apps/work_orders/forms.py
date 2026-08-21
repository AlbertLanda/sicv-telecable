"""
Formularios web del módulo de órdenes de trabajo.

Capa de presentación: recopilan los datos que el dominio necesita y acotan
lo que el usuario puede elegir al ámbito que le corresponde -el cliente que
se atiende, la sede de la orden-. Las reglas de negocio NO viven aquí: el
servicio y el modelo siguen siendo los que deciden si la operación procede.

El principio compartido es el mismo en ambos formularios: un campo que no se
declara no se puede enviar, y una opción que no está en el queryset no es
válida. Así, el POST manipulado se agota en la capa web sin que el dominio
tenga que confiar en ella.

- WorkOrderCreateForm no expone order_number, created_by, status,
  assigned_technician, cause ni result: el servicio los fija por su cuenta.
- WorkOrderAssignForm solo expone el técnico y una observación: el estado lo
  mueve assign_technician(), nunca el navegador.
"""

from django import forms

from apps.accounts.models import User
from apps.organization.models import Branch, Zone
from apps.services.models import Subscription
from apps.work_orders.models import (
    OrderReason,
    OrderSubtype,
    OrderType,
    WorkOrder,
)


class WorkOrderCreateForm(forms.ModelForm):
    """
    Datos de creación de una OT para un cliente concreto.

    Recibe el cliente ya resuelto por la vista (nunca por el navegador) y
    restringe los querysets a su ámbito: sus suscripciones, su sede, las zonas
    de esa sede y los catálogos activos. Lo que no está en el queryset no es
    una opción válida, así que una suscripción ajena o una zona de otra sede
    se rechazan como "opción no válida" sin llegar al servicio.
    """

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
        """
        Traduce los datos limpios a los argumentos de create_work_order().

        La vista no arma este diccionario a mano: si mañana cambia la firma
        del servicio, el ajuste ocurre en un solo lugar. `created_by` no
        aparece aquí a propósito: lo aporta la vista desde request.user.
        """
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
    """
    Asignación de una orden de trabajo a un técnico.

    Deliberadamente NO es un ModelForm: la asignación no es "guardar campos",
    es una transición de dominio. Sin form.save() no existe siquiera la
    tentación de persistir el técnico por fuera de assign_technician().

    El único control real de quién puede recibir la orden es el queryset:
    lo que no está en él no es una opción válida, así que un POST manipulado
    con un técnico inactivo, con un usuario administrativo o con un técnico
    de otra sede se rechaza aquí -como "opción no válida"- y nunca llega al
    dominio. Las validaciones del modelo siguen siendo la última palabra.
    """

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

        # -------------------------------------------------------------
        # TÉCNICOS ELEGIBLES
        #
        # Sin orden resuelta no se ofrece a nadie: antes un selector vacío
        # que uno que exponga personal de sedes ajenas.
        # -------------------------------------------------------------

        if order is None:
            return

        self.fields["assigned_technician"].queryset = (
            User.objects
            .filter(
                role=User.Role.TECHNICIAN,
                is_active=True,
                branch=order.branch_id,
            )
            .select_related("branch")
            .order_by("first_name", "last_name", "username")
        )
