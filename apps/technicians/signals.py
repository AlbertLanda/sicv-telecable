from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import User
from apps.technicians.models import TechnicianProfile


@receiver(post_save, sender=User)
def ensure_technician_profile(sender, instance, **kwargs):
    """Todo técnico operativo obtiene perfil de Red Interna por defecto."""
    if instance.role == User.Role.TECHNICIAN:
        TechnicianProfile.objects.get_or_create(user=instance)
