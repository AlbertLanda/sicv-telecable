from django.test import TestCase
from django.urls import reverse


class TechnicianPortalShellTests(TestCase):
    """El portal es un shell público; los datos reales siguen protegidos por la API token."""

    def test_portal_is_reachable_without_web_session(self):
        response = self.client.get(reverse("technician_portal:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Portal del técnico")
        self.assertContains(response, "Órdenes disponibles")
        self.assertContains(response, "Mis órdenes")

    def test_portal_points_to_token_api(self):
        response = self.client.get(reverse("technician_portal:home"))

        self.assertContains(response, "/api/technicians/login/")
        self.assertContains(response, "/api/technicians/me/")
        self.assertContains(response, "/api/technicians/work-orders/")

    def test_portal_contains_current_field_workflow_controls(self):
        response = self.client.get(reverse("technician_portal:home"))

        self.assertContains(response, "Ficha técnica")
        self.assertContains(response, "Caja NAP")
        self.assertContains(response, "Borne")
        self.assertContains(response, "MAC / Equipo")
        self.assertContains(response, "Material utilizado en domicilio")
        self.assertContains(response, "Material retirado de domicilio")
        self.assertContains(response, "Metraje y exceso de instalación")
        self.assertContains(response, "Cable UTP")
        self.assertContains(response, "Cable coaxial RG6")
        self.assertContains(response, "Fibra óptica Drop")
        self.assertContains(response, "Fotos y archivos")

    def test_installation_meterage_is_an_automatic_summary_not_a_second_form(self):
        response = self.client.get(reverse("technician_portal:home"))
        body = response.content.decode()

        self.assertIn(
            "Resumen automático de los cables instalados por metro",
            body,
        )
        self.assertIn(
            '<form id="materials-form" class="form-grid compact-form-grid" hidden>',
            body,
        )
        self.assertIn("material_excess_sync.js", body)

    def test_portal_keeps_textual_address_and_maps_action_visible(self):
        response = self.client.get(reverse("technician_portal:home"))

        self.assertContains(response, "Dirección")
        self.assertContains(response, "Referencia")
        self.assertContains(response, "Abrir en Google Maps")


class TechnicianPortalContractTests(TestCase):
    """El apartado Contrata y el visor donde el abonado firma.

    Son pruebas del shell, no del flujo: lo que se fija aquí es que la
    pantalla traiga el visor y el lienzo, y que el apartado nazca oculto.
    Quién puede firmar y cuándo lo decide la API, y eso se prueba en
    `test_api_contract_signature.py`.
    """

    def test_el_portal_trae_el_apartado_contrata(self):
        response = self.client.get(reverse("technician_portal:home"))

        self.assertContains(response, "Contrato del abonado")
        self.assertContains(response, "Dibujar firma")
        self.assertContains(response, "Ver contrato")

    def test_la_contrata_nace_oculta_y_la_descubre_la_api(self):
        """Solo las instalaciones traen contrato, y quién lo sabe es el servidor."""

        response = self.client.get(reverse("technician_portal:home"))

        self.assertContains(
            response,
            '<section id="contract-panel" class="panel" hidden>',
            html=False,
        )

    def test_el_visor_permite_leer_el_contrato_antes_de_firmarlo(self):
        response = self.client.get(reverse("technician_portal:home"))
        body = response.content.decode()

        # Zoom y desplazamiento: el abonado firma lo que puede leer.
        self.assertIn('id="signer-zoom-in"', body)
        self.assertIn('id="signer-zoom-out"', body)
        self.assertIn('id="signer-doc"', body)

        # Dibujar, colocar y aceptar: los tres pasos de la firma.
        self.assertIn('id="signature-canvas"', body)
        self.assertIn("Colocar firma", body)
        self.assertIn('id="signer-place"', body)
        self.assertIn("Aceptar y guardar", body)
        self.assertIn("Rechazar", body)

    def test_la_firma_se_mueve_y_se_estira_antes_de_aceptarla(self):
        """Nace sobre la línea, pero el técnico puede ajustarla."""

        body = self.client.get(reverse("technician_portal:home")).content.decode()

        self.assertIn('id="signer-place-handle"', body)
        self.assertIn("Arrastra la firma a su sitio", body)
        self.assertIn("Volver a dibujar", body)

    def test_la_firma_ya_registrada_se_puede_coger_del_documento(self):
        """Tocarla la despega del papel para moverla, medirla o quitarla."""

        body = self.client.get(reverse("technician_portal:home")).content.decode()

        self.assertIn("Toca la firma del contrato", body)
        self.assertIn("Eliminar firma", body)
        self.assertIn('id="signer-place-cancel"', body)

    def test_el_lienzo_deja_elegir_color_y_grosor(self):
        body = self.client.get(reverse("technician_portal:home")).content.decode()

        for control in ("Negro", "Azul", "Fino", "Medio", "Grueso"):
            self.assertIn(control, body)

    def test_el_visor_carga_pdfjs_desde_el_propio_servidor(self):
        """En el domicilio del abonado no se depende de un CDN."""

        response = self.client.get(reverse("technician_portal:home"))

        self.assertContains(response, "contract_signer.js")
        self.assertNotContains(response, "cdnjs")
