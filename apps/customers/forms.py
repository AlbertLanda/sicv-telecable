from django import forms

from .models import Customer, CustomerAddress


class CustomerInitialForm(forms.Form):
    """
    Pantalla 3:
    Datos mínimos para iniciar el registro del cliente.

    Los campos de nombres/apellidos personales solo son obligatorios
    para persona natural (DNI/CE/PASAPORTE). Para persona jurídica
    (RUC) no se exigen datos personales; la razón social se solicita
    en la Pantalla 4 (Datos generales).

    IMPORTANTE: esta obligatoriedad condicional se resuelve en
    clean(), es decir, del lado servidor. El JavaScript del template
    solo oculta/muestra campos para mejorar la experiencia de uso,
    pero no es la fuente de la validación.
    """

    document_type = forms.ChoiceField(
        label="Tipo de documento",
        choices=Customer.DocumentType.choices,
        widget=forms.Select(
            attrs={
                "class": "form-select",
                "id": "id_document_type",
            }
        ),
    )

    document_number = forms.CharField(
        label="Documento",
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "maxlength": "20",
            }
        ),
    )

    paternal_surname = forms.CharField(
        label="Apellido paterno",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": "100",
            }
        ),
    )

    maternal_surname = forms.CharField(
        label="Apellido materno",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": "100",
            }
        ),
    )

    first_name = forms.CharField(
        label="Nombres",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": "100",
            }
        ),
    )

    # Solo aplica a RUC (persona jurídica). Se completa mediante el
    # botón "Obtener datos" (consulta a SUNAT) o manualmente por el
    # usuario. Es un campo visible (igual que nombres/apellidos lo
    # son para persona natural) para que el operador vea y pueda
    # corregir la razón social apenas se consulta SUNAT. El valor
    # viaja a la sesión junto con el resto de datos de esta pantalla
    # para prellenar "Razón social" en la Pantalla 4
    # (CustomerGeneralDataView), donde puede volver a editarse.
    business_name = forms.CharField(
        label="Razón social",
        max_length=200,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": "200",
                "id": "id_business_name",
            }
        ),
    )

    def clean_business_name(self):
        return self.cleaned_data.get("business_name", "").strip()

    def clean_document_number(self):
        return self.cleaned_data["document_number"].strip().upper()

    def clean(self):
        cleaned_data = super().clean()

        document_type = cleaned_data.get("document_type")
        document_number = cleaned_data.get("document_number")

        if not document_type or not document_number:
            return cleaned_data

        # ---------------------------------------------------------
        # VALIDACIÓN DEL DOCUMENTO
        # ---------------------------------------------------------

        if document_type == Customer.DocumentType.DNI:

            if not document_number.isdigit():
                self.add_error(
                    "document_number",
                    "El DNI debe contener únicamente números.",
                )

            elif len(document_number) != 8:
                self.add_error(
                    "document_number",
                    "El DNI debe tener exactamente 8 dígitos.",
                )

        elif document_type == Customer.DocumentType.RUC:

            if not document_number.isdigit():
                self.add_error(
                    "document_number",
                    "El RUC debe contener únicamente números.",
                )

            elif len(document_number) != 11:
                self.add_error(
                    "document_number",
                    "El RUC debe tener exactamente 11 dígitos.",
                )

        elif document_type in (
            Customer.DocumentType.CE,
            Customer.DocumentType.PASSPORT,
        ):

            if not document_number:
                self.add_error(
                    "document_number",
                    "El documento es obligatorio.",
                )

        # ---------------------------------------------------------
        # VALIDACIÓN DE DATOS PERSONALES SEGÚN TIPO DE PERSONA
        #
        # Persona natural (DNI/CE/PASAPORTE): nombres y apellido
        # paterno son obligatorios.
        # Persona jurídica (RUC): no se exigen datos personales.
        # ---------------------------------------------------------

        person_type = Customer.person_type_for_document(document_type)

        if person_type == Customer.PersonType.NATURAL:

            if not (cleaned_data.get("first_name") or "").strip():
                self.add_error(
                    "first_name",
                    "Los nombres son obligatorios para persona natural.",
                )

            if not (cleaned_data.get("paternal_surname") or "").strip():
                self.add_error(
                    "paternal_surname",
                    (
                        "El apellido paterno es obligatorio para "
                        "persona natural."
                    ),
                )

        # ---------------------------------------------------------
        # VALIDACIÓN DE DUPLICADO
        # ---------------------------------------------------------

        if not self.errors:

            exists = Customer.objects.filter(
                document_type=document_type,
                document_number=document_number,
                is_active=True,
            ).exists()

            if exists:
                self.add_error(
                    "document_number",
                    (
                        "Ya existe un cliente registrado con este "
                        "tipo y número de documento."
                    ),
                )

        return cleaned_data


class CustomerRegistrationForm(forms.ModelForm):
    """
    Pantalla 4:
    Datos generales del cliente.

    Los datos básicos de identidad vienen de la Pantalla 3
    mediante la sesión.

    NOTA IMPORTANTE:
    "person_type" NO es un campo editable de este formulario. Se
    deriva siempre del tipo de documento (Customer.person_type_for_
    document), tal como exige la regla de correspondencia
    documento/tipo de persona. Esto evita que la interfaz permita
    combinaciones incoherentes (p. ej. RUC + Persona Natural) y hace
    que la regla se cumpla también del lado servidor, sin depender
    de lo que el usuario seleccione.

    El tipo de documento se recibe en __init__ (no en los datos del
    formulario) para poder calcular el tipo de persona esperado y
    exigir la razón social cuando corresponda.
    """

    class Meta:
        model = Customer

        fields = [
            "branch",
            "business_name",
            "phone",
            "secondary_phone",
            "email",
        ]

        widgets = {
            "branch": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": "20",
                }
            ),
            "secondary_phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": "20",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "maxlength": "254",
                }
            ),
            "business_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": "200",
                }
            ),
        }

        labels = {
            "branch": "Sede",
            "phone": "Teléfono principal",
            "secondary_phone": "Teléfono secundario",
            "email": "Correo electrónico",
            "business_name": "Razón social / Nombre comercial",
        }

    def __init__(self, *args, document_type=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.document_type = document_type
        self.person_type = Customer.person_type_for_document(document_type)

        # El campo solo es obligatorio a nivel de negocio para
        # persona jurídica; se deja opcional a nivel de Django para
        # que la validación real ocurra en clean(), donde se conoce
        # el tipo de persona derivado del documento.
        self.fields["business_name"].required = False

    def clean(self):
        cleaned_data = super().clean()

        business_name = (cleaned_data.get("business_name") or "").strip()

        if (
            self.person_type == Customer.PersonType.LEGAL
            and not business_name
        ):
            self.add_error(
                "business_name",
                "La razón social es obligatoria para una persona jurídica.",
            )

        return cleaned_data


class CustomerAddressForm(forms.ModelForm):

    class Meta:
        model = CustomerAddress

        fields = [
            "zone",
            "address",
            "reference",
            "district",
            "meter_number",
            "latitude",
            "longitude",
            "gps_link",
            "is_primary",
        ]

        widgets = {
            "zone": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "address": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": "250",
                    "autocomplete": "street-address",
                }
            ),
            "reference": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "maxlength": "300",
                    "rows": 2,
                }
            ),
            "district": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": "120",
                }
            ),
            "meter_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": "50",
                }
            ),
            "latitude": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.0000001",
                }
            ),
            "longitude": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.0000001",
                }
            ),
            "gps_link": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "maxlength": "500",
                    "placeholder": "https://maps.google.com/...",
                }
            ),
            "is_primary": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

        labels = {
            "zone": "Zona",
            "address": "Dirección",
            "reference": "Referencia",
            "district": "Distrito",
            "meter_number": "Número de medidor",
            "latitude": "Latitud",
            "longitude": "Longitud",
            "gps_link": "Enlace GPS",
            "is_primary": "Dirección principal",
        }

    def clean_address(self):
        return self.cleaned_data.get("address", "").strip()

    def clean_reference(self):
        return self.cleaned_data.get("reference", "").strip()

    def clean_district(self):
        return self.cleaned_data.get("district", "").strip()

    def clean_meter_number(self):
        return self.cleaned_data.get("meter_number", "").strip()