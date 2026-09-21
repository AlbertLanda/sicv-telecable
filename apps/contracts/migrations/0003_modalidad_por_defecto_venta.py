"""La modalidad habitual es la venta.

El alta abre en ella en vez de obligar a elegir lo que casi siempre es lo
mismo. Con un valor por defecto, Django deja de ofrecer la opcion vacia en el
combo: la modalidad de un contrato nuevo siempre es una de las cuatro.

Los contratos anteriores no se tocan. Su modalidad quedo vacia porque el dato
no se registraba, y ponerles «venta» ahora seria inventar como recibieron un
equipo que nadie anoto.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0002_contrato_de_servicio'),
    ]

    operations = [
        migrations.AlterField(
            model_name='contract',
            name='modality',
            field=models.CharField(choices=[('SALE', 'Venta'), ('RENTAL', 'Alquiler'), ('OWNED', 'Propio'), ('LOAN', 'Préstamo')], default='SALE', help_text='Cómo recibe el abonado el equipo del servicio contratado. La venta es lo habitual, así que el alta abre en ella.', max_length=20, verbose_name='Modalidad'),
        ),
    ]
