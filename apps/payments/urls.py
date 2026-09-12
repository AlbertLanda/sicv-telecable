from django.urls import path

from . import views


app_name = "payments"


urlpatterns = [

    # --------------------------------------------------------------
    # Cuenta de un abonado concreto.
    #
    # Todas llevan pk. Son pestañas de la ficha del cliente, no entradas
    # del menú lateral: se navega primero al abonado y después a su
    # cuenta, así que no hay pantalla de cobranza sin abonado a la vista.
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

    # El mismo comprobante como archivo. Cuelga del comprobante y no del
    # abonado porque es el mismo documento por otra salida, no otra pantalla.
    path(
        "comprobantes/<int:pk>/pdf/",
        views.ReceiptPdfView.as_view(),
        name="receipt_pdf",
    ),
    path(
        "pagos/<int:pk>/anular/",
        views.PaymentVoidView.as_view(),
        name="void",
    ),
]
