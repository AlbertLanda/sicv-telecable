from django.urls import path

from . import views


app_name = "payments"


urlpatterns = [

    # --------------------------------------------------------------
    # Entradas del menú lateral.
    #
    # No llevan pk: resuelven el abonado seleccionado en la sesión, que
    # es como se navega en ventanilla -primero se ubica al cliente y
    # después se mira su cuenta.
    # --------------------------------------------------------------
    path(
        "deuda/",
        views.SelectedCustomerRedirectView.as_view(screen="payments:debt"),
        name="selected_debt",
    ),
    path(
        "historial/",
        views.SelectedCustomerRedirectView.as_view(screen="payments:history"),
        name="selected_history",
    ),
    path(
        "comprobantes/",
        views.SelectedCustomerRedirectView.as_view(screen="payments:receipts"),
        name="selected_receipts",
    ),

    # --------------------------------------------------------------
    # Cuenta de un abonado concreto.
    # --------------------------------------------------------------
    path(
        "clientes/<int:pk>/deuda/",
        views.CustomerDebtView.as_view(),
        name="debt",
    ),
    path(
        "clientes/<int:pk>/historial/",
        views.CustomerPaymentHistoryView.as_view(),
        name="history",
    ),
    path(
        "clientes/<int:pk>/comprobantes/",
        views.CustomerReceiptsView.as_view(),
        name="receipts",
    ),
    path(
        "clientes/<int:pk>/cobrar/",
        views.PaymentRegisterView.as_view(),
        name="register",
    ),

    # Boton "Nuevo": emitir un cargo que el ciclo mensual no genera.
    path(
        "clientes/<int:pk>/deuda/nueva/",
        views.ChargeCreateView.as_view(),
        name="charge_create",
    ),

    # Boton "Compromiso": aplazar el corte de cargos concretos.
    path(
        "clientes/<int:pk>/compromiso/",
        views.PaymentCommitmentCreateView.as_view(),
        name="commitment_create",
    ),
    path(
        "compromisos/<int:pk>/anular/",
        views.PaymentCommitmentCancelView.as_view(),
        name="commitment_cancel",
    ),

    # --------------------------------------------------------------
    # Comprobante y anulación.
    # --------------------------------------------------------------
    path(
        "comprobantes/<int:pk>/",
        views.ReceiptDetailView.as_view(),
        name="receipt_detail",
    ),
    path(
        "pagos/<int:pk>/anular/",
        views.PaymentVoidView.as_view(),
        name="void",
    ),
]
