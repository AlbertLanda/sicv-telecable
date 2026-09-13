from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch, Office


class ActiveBranchTests(TestCase):
    """
    Sede activa: desde qué sede se consulta, no a qué sede pertenece el
    operador.

    La regla de negocio que fijan estas pruebas es que un ATC de Huancayo
    puede atender a un abonado de Oroya sin derivar la llamada, y que
    hacerlo no cambia su asignación.
    """

    def setUp(self):
        self.huancayo = Branch.objects.get(
            code="HUANCAYO",
        )

        self.huancayo_office = Office.objects.create(
            branch=self.huancayo,
            code="HYO-01",
            name="Oficina Principal",
        )

        self.oroya = Branch.objects.get(
            code="OROYA",
        )
        self.inactiva = Branch.objects.create(
            code="OLD",
            name="Sede cerrada",
            is_active=False,
        )

        self.user = User.objects.create_user(
            username="atc1",
            password="ClaveSegura123",
            role=User.Role.ATC,
            branch=self.huancayo,
        )
        self.client.login(username="atc1", password="ClaveSegura123")
        self.url = reverse("organization:set_active_branch")

    def test_active_branch_defaults_to_the_users_own_branch(self):
        response = self.client.get(reverse("customers:search"))

        self.assertEqual(response.context["active_branch"], self.huancayo)

    def test_operator_can_switch_to_another_branch(self):
        self.client.post(self.url, {"branch": self.oroya.pk})

        response = self.client.get(reverse("customers:search"))

        self.assertEqual(response.context["active_branch"], self.oroya)

    def test_switching_branch_does_not_change_the_users_assignment(self):
        self.client.post(self.url, {"branch": self.oroya.pk})

        self.user.refresh_from_db()
        self.assertEqual(self.user.branch, self.huancayo)

    def test_inactive_branch_is_rejected(self):
        response = self.client.post(self.url, {"branch": self.inactiva.pk})

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(ACTIVE_BRANCH_SESSION_KEY, self.client.session)

    def test_unknown_branch_is_rejected(self):
        response = self.client.post(self.url, {"branch": 999999})

        self.assertEqual(response.status_code, 404)

    def test_get_is_not_allowed(self):
        """Cambiar el ámbito de consulta no debe ocurrir por una visita."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

    def test_anonymous_user_cannot_switch_branch(self):
        self.client.logout()

        response = self.client.post(self.url, {"branch": self.oroya.pk})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.headers["Location"])

    def test_changing_branch_lands_on_the_search(self):
        """Cambiar de sede deja atrás lo que se estaba mirando.

        No tiene sentido seguir viendo la ficha de un abonado de Jauja con la
        barra diciendo Oroya: la pantalla entera pasa a hablar de otro sitio.
        Antes se volvía a la pantalla anterior y el operador se quedaba
        delante de un abonado que ya no era del padrón que tenía elegido.
        """
        response = self.client.post(self.url, {"branch": self.oroya.pk})

        self.assertRedirects(response, reverse("customers:search"))

    def test_changing_branch_is_no_springboard_to_another_site(self):
        """El destino no lo decide el formulario, así que no hay a dónde ir.

        Cuando el destino venía en un campo del POST había que validarlo
        contra el propio host. Ahora es fijo: se comprueba que un intento de
        colarlo no llega a ninguna parte.
        """
        response = self.client.post(self.url, {
            "branch": self.oroya.pk,
            "next": "https://sitio-externo.example.com/",
        })

        self.assertRedirects(response, reverse("customers:search"))

    def test_changing_branch_forgets_the_customer_being_consulted(self):
        """El abonado elegido era del padrón de la sede anterior.

        Las entradas de cuenta del menú resuelven el abonado por la sesión, y
        dejarlo puesto haría que siguieran abriendo a alguien de la otra sede
        con la barra ya cambiada.
        """
        session = self.client.session
        session["selected_customer_id"] = 12345
        session.save()

        self.client.post(self.url, {"branch": self.oroya.pk})

        self.assertNotIn("selected_customer_id", self.client.session)

    def test_changing_office_lands_on_the_search_too(self):
        """La ventanilla decide de qué talonarios se emite.

        Una pantalla de cobro armada con las series de una oficina deja de
        valer en cuanto se elige otra, así que se vuelve al buscador en vez
        de dejar delante un formulario que ya no corresponde.
        """
        response = self.client.post(
            reverse("organization:set_active_office"),
            {"office": self.huancayo_office.pk},
        )

        self.assertRedirects(response, reverse("customers:search"))

    def test_changing_office_keeps_the_customer(self):
        """La sede no ha cambiado, así que el abonado sigue siendo de aquí.

        Soltarlo sería perder un dato que sigue valiendo: lo que deja de
        valer es la pantalla, y de eso ya se encarga volver al buscador.
        """
        session = self.client.session
        session["selected_customer_id"] = 12345
        session.save()

        self.client.post(
            reverse("organization:set_active_office"),
            {"office": self.huancayo_office.pk},
        )

        self.assertEqual(self.client.session["selected_customer_id"], 12345)

    def test_user_without_branch_defaults_to_huancayo(self):
        self.user.branch = None
        self.user.office = None
        self.user.save(update_fields=["branch", "office"])

        response = self.client.get(reverse("customers:search"))

        self.assertEqual(
            response.context["active_branch"],
            self.huancayo,
        )


    def test_user_without_office_defaults_to_first_active_office(self):
        """Sin oficina asignada se resuelve la primera de la sede, por nombre.

        No se compara contra la oficina que crea esta prueba: el padron real
        se siembra por migracion, asi que la sede llega con las suyas y la
        primera puede ser cualquiera de ellas. Lo que se fija es la regla.
        """
        self.user.office = None
        self.user.save(update_fields=["office"])

        esperada = (
            Office.objects
            .filter(branch=self.huancayo, is_active=True, is_deposit=False)
            .order_by("name", "pk")
            .first()
        )

        response = self.client.get(reverse("customers:search"))

        self.assertEqual(response.context["active_office"], esperada)

    def test_the_deposit_is_never_the_office_chosen_by_default(self):
        """Del deposito no se atiende a nadie.

        Es donde cae lo que llega por banco. Si el sistema lo eligiera solo,
        los cobros de un operador recien creado dirian que el dinero entro
        por transferencia sin que nadie lo haya dicho.
        """
        Office.objects.filter(branch=self.huancayo).update(is_active=False)

        deposito = Office.objects.create(
            branch=self.huancayo,
            code="HYO-DEP",
            name="A Deposito",
            is_deposit=True,
        )

        self.user.office = None
        self.user.save(update_fields=["office"])

        response = self.client.get(reverse("customers:search"))

        self.assertIsNone(response.context["active_office"])
        self.assertNotEqual(response.context["active_office"], deposito)

    def test_the_deposit_is_offered_in_the_top_bar(self):
        """El deposito se elige donde se elige todo lo demas.

        Quien cobra una transferencia lo elige aqui antes de registrarla: la
        pantalla de cobro no vuelve a preguntarlo, solo muestra lo elegido.
        Quien puede hacerlo es una decision de rol todavia sin tomar.
        """
        deposito = Office.objects.create(
            branch=self.huancayo,
            code="HYO-DEP2",
            name="Deposito",
            is_deposit=True,
        )

        response = self.client.get(reverse("customers:search"))

        self.assertIn(
            self.huancayo_office,
            response.context["available_offices"],
        )
        self.assertIn(deposito, response.context["available_offices"])
