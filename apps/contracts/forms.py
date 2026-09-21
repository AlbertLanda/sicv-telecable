from django import forms

from .models import Contract
from .subscriptions import resolver_suscripcion
from apps.accounts.models import User
from apps.services.models import Plan, ServiceType
from apps.work_orders.models import OrderReason, WorkOrder


class ContractCreateForm(forms.ModelForm):
    """Alta del contrato de servicio.

    Mantiene los campos y el orden del sistema anterior -servicio, plan,
    suscripcion, estado, modalidad, cuotas, inicio- porque es la pantalla que
    ATC tiene aprendida. Cuatro de ellos no se escriben: codigo y numero los
    pone el sistema, la suscripcion la resuelven el servicio y el plan, y el
    estado de un contrato nuevo es activo. La pantalla los muestra
    bloqueados para que se reconozcan.

    Servicio manda sobre plan, y los dos sobre la suscripcion que recibe el
    contrato. El combo de planes se repinta en el navegador con el catalogo
    que la vista deja en la pagina; aqui todo se vuelve a resolver y a
    comprobar, porque un POST armado a mano no pasa por ese javascript.
    """

    class Meta:
        model = Contract

        fields = [
            "service_type",
            "plan",
            "modality",
            "installments",
            "start_date",
            "playhub_email",
            "playhub_phone",
        ]

        widgets = {
            "service_type": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "plan": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "modality": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "installments": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": 1,
                    "step": 1,
                }
            ),
            # `<input type="date">` solo entiende el formato ISO. Sin
            # decirselo, Django pinta el valor en el formato local -21/09/2026-
            # y el navegador lo descarta: el campo salia vacio aunque el
            # formulario llegara con la fecha de hoy puesta.
            "start_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "playhub_email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "correo@dominio.com",
                }
            ),
            "playhub_phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "9XXXXXXXX",
                }
            ),
        }

        labels = {
            "service_type": "Servicio",
            "plan": "Plan",
            "modality": "Modalidad",
            "installments": "Cuotas",
            "start_date": "Inicio",
            "playhub_email": "Correo PlayHub",
            "playhub_phone": "Celular PlayHub",
        }

    def __init__(self, *args, **kwargs):
        customer = kwargs.pop("customer", None)

        super().__init__(*args, **kwargs)

        self.customer = customer

        self.fields["service_type"].queryset = (
            ServiceType.objects
            .filter(is_active=True)
            .order_by("name")
        )
        self.fields["service_type"].empty_label = "Seleccione un servicio"

        # Todos los planes activos: cual corresponde lo decide el servicio, y
        # eso se comprueba en el modelo. Limitar la lista aqui al servicio ya
        # elegido obligaria a reconstruir el formulario en cada cambio del
        # combo, que es justo lo que el catalogo en la pagina evita.
        self.fields["plan"].queryset = (
            Plan.objects
            .filter(is_active=True)
            .select_related("service_type")
            .order_by("service_type__name", "name")
        )
        self.fields["plan"].empty_label = "Seleccione un plan"

        # PlayHub solo se exige donde significa algo, y eso lo dice el
        # servicio. El formulario los declara opcionales y el modelo decide:
        # asi un servicio nuevo que manana se entregue por cuenta no
        # necesita tocar esta pantalla.
        self.fields["playhub_email"].required = False
        self.fields["playhub_phone"].required = False

        # La suscripción que recibe el contrato la resuelve `clean()` a
        # partir del servicio y el plan: no es un campo que el operador
        # llene. `subscription_resuelta` queda disponible para que la vista
        # la pinte bloqueada y para las pruebas.
        self.subscription_resuelta = None

    def clean(self):
        cleaned_data = super().clean()

        service_type = cleaned_data.get("service_type")
        plan = cleaned_data.get("plan")

        # ---------------------------------------------------------
        # RESOLVER LA SUSCRIPCIÓN
        #
        # No se elige: la determinan el cliente, el servicio y el plan. Si
        # no hay ninguna disponible, el contrato no tiene sobre qué
        # firmarse y lo que falta es registrar la suscripción, no corregir
        # un campo de esta pantalla. Por eso el aviso va arriba y no
        # colgando de un campo.
        # ---------------------------------------------------------

        if service_type and plan and self.customer:

            subscription = resolver_suscripcion(
                self.customer,
                service_type,
                plan,
            )

            if subscription is None:
                self.add_error(
                    None,
                    (
                        "Este cliente no tiene una suscripción en Preventa "
                        "disponible para el servicio y plan elegidos. "
                        "Regístrela antes de contratar."
                    ),
                )

            else:
                self.subscription_resuelta = subscription
                self.instance.subscription = subscription

        return cleaned_data


class InstallationWorkOrderForm(forms.Form):
    """
    Datos que ATC ingresa al generar la Orden de Instalación desde el
    resumen de contratación: observaciones, prioridad, motivo y vendedor.

    La instalación FTTH es siempre trabajo de campo. El formulario mantiene
    `attention_type` únicamente como dato explícito del contrato existente,
    pero restringido a FIELD para que ATC no pueda crear una instalación
    SYSTEM/NOC que después no aparecería en el canal técnico.

    No es un ModelForm de WorkOrder ni expone `subscription` ni `order_type`:
    create_installation_work_order() sigue siendo la fachada oficial.
    """

    detail = forms.CharField(
        required=False,
        label="Observaciones",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": (
                    "Observaciones operativas para el técnico..."
                ),
            }
        ),
    )

    priority = forms.ChoiceField(
        choices=WorkOrder.Priority.choices,
        required=False,
        initial=WorkOrder.Priority.NORMAL,
        label="Prioridad",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    reason = forms.ModelChoiceField(
        queryset=OrderReason.objects.none(),
        required=False,
        label="Motivo",
        empty_label="Sin motivo",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    # Una instalación FTTH que llega al técnico debe nacer en FIELD. Se deja
    # como selector de una sola opción para no romper la plantilla ni el
    # contrato actual de la vista, pero un POST manipulado con SYSTEM queda
    # invalidado por ChoiceField antes de llamar al dominio.
    attention_type = forms.ChoiceField(
        choices=[
            (
                WorkOrder.AttentionType.FIELD,
                WorkOrder.AttentionType.FIELD.label,
            ),
        ],
        required=False,
        initial=WorkOrder.AttentionType.FIELD,
        label="Tipo de atención",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    seller = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="Vendedor",
        empty_label="Sin vendedor",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Solo motivos activos del catálogo de INSTALACIÓN: el mismo
        # criterio de alcance que ya aplica WorkOrderCreateForm para el
        # resto de tipos de orden.
        self.fields["reason"].queryset = (
            OrderReason.objects
            .filter(
                order_type__code="INSTALLATION",
                is_active=True,
            )
            .order_by("name")
        )

        # Solo usuarios activos con rol Ventas: el mismo criterio que
        # _validate_seller exige en el servicio, para que el formulario
        # nunca ofrezca una opción que el servicio vaya a rechazar.
        self.fields["seller"].queryset = (
            User.objects
            .filter(
                role=User.Role.SALES,
                is_active=True,
            )
            .order_by("first_name", "last_name", "username")
        )
