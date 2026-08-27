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


class WorkOrderDispatchFilterForm(forms.Form):
    """
    Filtros de la bandeja operativa de despacho.

    Decisiones deliberadas:

    - Es un forms.Form y no un ModelForm: no describe una orden, describe la
      consulta. Todos sus campos son opcionales, de modo que abrir la bandeja
      sin parámetros es un formulario válido y vacío.
    - Los ModelChoiceField hacen el saneamiento de la entrada. Un ?branch=999
      o un ?status=CUALQUIERCOSA no llega nunca al queryset: se queda en
      form.errors y el filtro simplemente no se aplica. Por eso la vista no
      construye ningún filtro con SQL manual ni interpola texto del usuario.
    - Los catálogos del filtro NO se acotan a is_active. Un filtro sirve para
      encontrar lo que ya existe: si una sede, una zona, un tipo o un técnico
      se desactivan después, sus órdenes deben seguir siendo consultables.
      El formulario de creación sí acota a activos, porque ahí se decide qué
      se puede registrar de nuevo.
    - sede y zona son criterios de organización del listado. Este formulario
      no toca en ningún punto la elegibilidad del técnico: esa la resuelve
      WorkOrderAssignForm y sigue admitiendo técnicos de otra sede.
    """

    # Valor sentinela del filtro de técnico. No es un pk, así que no puede
    # colisionar con un usuario real.
    UNASSIGNED = "unassigned"

    q = forms.CharField(
        required=False,
        label="Buscar",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": (
                    "N.º de orden, código de cliente, documento o nombre..."
                ),
            }
        ),
    )

    status = forms.ChoiceField(
        required=False,
        label="Estado",
        choices=[("", "Todos los estados")] + list(WorkOrder.Status.choices),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    branch = forms.ModelChoiceField(
        required=False,
        label="Sede",
        queryset=Branch.objects.order_by("name"),
        empty_label="Todas las sedes",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    zone = forms.ModelChoiceField(
        required=False,
        label="Zona",
        queryset=(
            Zone.objects
            .select_related("branch")
            .order_by("branch__name", "name")
        ),
        empty_label="Todas las zonas",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    order_type = forms.ModelChoiceField(
        required=False,
        label="Tipo de orden",
        queryset=OrderType.objects.order_by("name"),
        empty_label="Todos los tipos",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    priority = forms.ChoiceField(
        required=False,
        label="Prioridad",
        choices=[("", "Todas las prioridades")] + list(
            WorkOrder.Priority.choices
        ),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    technician = forms.ChoiceField(
        required=False,
        label="Técnico",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Las opciones de técnico se arman en __init__ y no en la definición
        # del campo: una lista de choices evaluada al importar el módulo se
        # quedaría congelada con los usuarios que existían en ese momento.
        technicians = (
            User.objects
            .filter(role=User.Role.TECHNICIAN)
            .select_related("branch")
            .order_by("first_name", "last_name", "username")
        )

        self.fields["technician"].choices = (
            [
                ("", "Todos los técnicos"),
                (self.UNASSIGNED, "Sin asignar"),
            ]
            + [(str(user.pk), str(user)) for user in technicians]
        )

    def clean_q(self):
        return self.cleaned_data.get("q", "").strip()

    def selected_filters(self):
        """
        Filtros que superaron la validación.

        Se llama a is_valid() para forzar el saneamiento y luego se lee
        cleaned_data, que solo contiene los campos que pasaron. Así un
        parámetro corrupto anula su propio filtro sin arrastrar consigo a los
        demás: ?branch=999&status=PENDING sigue filtrando por estado.
        """
        self.is_valid()

        return getattr(self, "cleaned_data", {})

    def apply_to(self, queryset):
        """Aplica al queryset los filtros presentes y válidos."""
        data = self.selected_filters()

        term = data.get("q")

        if term:
            queryset = self._search(queryset, term)

        for field, lookup in (
            ("status", "status"),
            ("branch", "branch"),
            ("zone", "zone"),
            ("order_type", "order_type"),
            ("priority", "priority"),
        ):
            value = data.get(field)

            if value:
                queryset = queryset.filter(**{lookup: value})

        technician = data.get("technician")

        if technician == self.UNASSIGNED:
            queryset = queryset.filter(assigned_technician__isnull=True)

        elif technician:
            queryset = queryset.filter(assigned_technician_id=technician)

        return queryset

    def _search(self, queryset, term):
        """
        Búsqueda por número de orden y por identidad del cliente.

        Se filtra palabra por palabra en AND -mismo criterio que la búsqueda
        de clientes-, de modo que "Juan Pérez" exige ambas coincidencias. Todo
        se expresa con Q() del ORM: no hay extra(), ni raw(), ni cadenas SQL
        construidas con datos del operador.
        """
        for word in term.split():
            queryset = queryset.filter(
                Q(order_number__icontains=word)
                | Q(subscription__customer__code__icontains=word)
                | Q(subscription__customer__document_number__icontains=word)
                | Q(subscription__customer__business_name__icontains=word)
                | Q(subscription__customer__first_name__icontains=word)
                | Q(subscription__customer__paternal_surname__icontains=word)
                | Q(subscription__customer__maternal_surname__icontains=word)
            )

        return queryset
