# Declara el permiso funcional work_orders.start_workorder.
#
# Solo altera Meta.options: no toca campos, ni datos, ni la máquina de
# estados. Es la contrapartida en base de datos del permiso que autoriza la
# vista de inicio de atención, del mismo modo que 0010 declaró
# assign_workorder para la de asignación.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('work_orders', '0010_alter_workorder_options'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='workorder',
            options={'ordering': ['-created_at'], 'permissions': [('assign_workorder', 'Puede asignar órdenes de trabajo a un técnico'), ('start_workorder', 'Puede iniciar la atención de órdenes de trabajo')], 'verbose_name': 'Orden de trabajo', 'verbose_name_plural': 'Órdenes de trabajo'},
        ),
    ]
