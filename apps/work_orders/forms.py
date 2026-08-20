"""
Formulario web de creación de órdenes de trabajo.

Capa de presentación: recopila los datos que create_work_order() necesita y
acota lo que el usuario puede elegir al ámbito del cliente que se está
atendiendo. Las reglas de negocio NO viven aquí: el servicio de dominio sigue
siendo el que decide si la orden puede registrarse.

El formulario deliberadamente NO expone order_number, created_by, status,
assigned_technician, cause ni result. Al no declararlos en Meta.fields, un
POST manipulado que los incluya simplemente no los alcanza: Django los
descarta y el servicio los fija por su cuenta.
"""

from django import forms

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
