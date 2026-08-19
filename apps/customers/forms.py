from django import forms

from .models import Customer, CustomerAddress


class CustomerInitialForm(forms.Form):
    """
    Pantalla 3:
    Datos mínimos para iniciar el registro del cliente.
    """

    document_type = forms.ChoiceField(
        label="Tipo de documento",
        choices=Customer.DocumentType.choices,
        widget=forms.Select(
            attrs={
                "class": "form-select",
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
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": "100",
            }
        ),
    )

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
    """

    class Meta:
        model = Customer

        fields = [
            "branch",
            "person_type",
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
            "person_type": forms.Select(
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
            "person_type": "Tipo de persona",
            "phone": "Teléfono principal",
            "secondary_phone": "Teléfono secundario",
            "email": "Correo electrónico",
            "business_name": "Razón social / Nombre comercial",
        }

    def clean(self):
        cleaned_data = super().clean()

        person_type = cleaned_data.get("person_type")
        business_name = cleaned_data.get("business_name", "").strip()

        if (
            person_type == Customer.PersonType.LEGAL
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