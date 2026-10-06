"""¿Va a salir el logotipo en el comprobante?

Existe porque el fallo es mudo: sin el archivo, el PDF se imprime igual y sin
logo -que es lo que queremos, para que la ventanilla no se pare-, así que
mirar el papel no distingue «falta la imagen» de «está mal puesta». Esto lo
dice en una línea, sin generar un comprobante ni abrirlo.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.organization import branding
from apps.payments.pdf import LOGO_STEM, LOGO_SUFFIXES, find_logo


class Command(BaseCommand):
    help = "Comprueba si el logotipo del comprobante está donde se le espera."

    def handle(self, *args, **options):
        try:
            ruta = find_logo()
        except Exception:
            raise CommandError(
                "No se pudo consultar el almacenamiento MEDIA. Revise su "
                "configuración, disponibilidad y permisos de lectura/listado."
            ) from None

        if ruta is None:
            self.stdout.write(self.style.WARNING(
                "No hay logotipo. El comprobante se imprimirá sin él."
            ))
            self.stdout.write("")
            self.stdout.write(
                f"  Guarde {LOGO_STEM}.png en la raíz del almacenamiento MEDIA "
                "configurado en Django (disco local o contenedor privado)."
            )
            self.stdout.write(
                f"  Vale cualquier extensión ({', '.join(LOGO_SUFFIXES)}) y lo "
                f"que el navegador le pegue detrás del nombre."
            )
            return

        # Se abre de verdad, no solo se comprueba que el archivo exista: un
        # PNG truncado o un archivo con la extensión cambiada a mano pasan la
        # comprobación de existencia y revientan al imprimir.
        try:
            from reportlab.platypus import Image

            imagen = Image(branding.fuente_de_imagen(ruta))
            medidas = f"{imagen.imageWidth}x{imagen.imageHeight} px"
        except Exception:
            raise CommandError(
                "Se encontró el logotipo, pero no se pudo leer como imagen. "
                "Revise el archivo y los permisos de lectura de MEDIA."
            ) from None

        self.stdout.write(self.style.SUCCESS(
            f"Logotipo listo: {ruta.name} ({medidas})"
        ))
