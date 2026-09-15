"""¿Va a salir el logotipo en el comprobante?

Existe porque el fallo es mudo: sin el archivo, el PDF se imprime igual y sin
logo -que es lo que queremos, para que la ventanilla no se pare-, así que
mirar el papel no distingue «falta la imagen» de «está mal puesta». Esto lo
dice en una línea, sin generar un comprobante ni abrirlo.
"""

from django.core.management.base import BaseCommand

from apps.payments.pdf import LOGO_DIR, LOGO_STEM, LOGO_SUFFIXES, find_logo


class Command(BaseCommand):
    help = "Comprueba si el logotipo del comprobante está donde se le espera."

    def handle(self, *args, **options):
        ruta = find_logo()

        if ruta is None:
            self.stdout.write(self.style.WARNING(
                "No hay logotipo. El comprobante se imprimirá sin él."
            ))
            self.stdout.write("")
            self.stdout.write(
                f"  Guarde la imagen aquí:  {LOGO_DIR / (LOGO_STEM + '.png')}"
            )
            self.stdout.write(
                f"  Vale cualquier extensión ({', '.join(LOGO_SUFFIXES)}) y lo "
                f"que el navegador le pegue detrás del nombre."
            )
            self.stdout.write("")

            existentes = sorted(
                p.name for p in LOGO_DIR.glob("*") if p.is_file()
            ) if LOGO_DIR.exists() else []

            self.stdout.write(
                f"  En {LOGO_DIR} hay ahora: "
                f"{', '.join(existentes) if existentes else '(nada)'}"
            )

            return

        # Se abre de verdad, no solo se comprueba que el archivo exista: un
        # PNG truncado o un archivo con la extensión cambiada a mano pasan la
        # comprobación de existencia y revientan al imprimir.
        try:
            from reportlab.platypus import Image

            imagen = Image(str(ruta))
            medidas = f"{imagen.imageWidth}x{imagen.imageHeight} px"
        except Exception as error:
            self.stdout.write(self.style.ERROR(
                f"El archivo {ruta.name} está, pero no se puede leer como "
                f"imagen: {error}"
            ))

            return

        self.stdout.write(self.style.SUCCESS(
            f"Logotipo listo: {ruta.name} ({medidas})"
        ))
        self.stdout.write(f"  {ruta}")
