
# from django.db.models.signals import post_save
# from django.dispatch import receiver
# from django.contrib.auth.models import User
# from .models import empProfile

# @receiver(post_save, sender=User)
# def create_profile(sender, instance, created, **kwargs):
#     if created:
#         role = 'SUPER_ADMIN' if instance.is_superuser else 'EMPLOYEE'
#         empProfile.objects.create(user=instance, role=role)

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import empProfile, ShiftMaster


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    """
    Automatically create an employee profile whenever a new Django User
    is created.

    Normal employees receive:
    - The active default shift
    - The active default manager

    Superusers:
    - Receive the SUPER_ADMIN role
    - Do not receive a reporting manager
    - Can still receive the default shift
    """

    if not created:
        return

    # Defensive check to avoid duplicate profiles.
    if empProfile.objects.filter(user=instance).exists():
        return

    role = "SUPER_ADMIN" if instance.is_superuser else "EMPLOYEE"

    default_shift = ShiftMaster.objects.filter(
        is_default=True,
        is_active=True
    ).first()

    default_manager = None

    if not instance.is_superuser:
        default_manager = empProfile.objects.filter(
            is_default_manager=True,
            is_active=True
        ).select_related(
            "user"
        ).first()

    empProfile.objects.create(
        user=instance,
        role=role,
        shift=default_shift,
        manager=default_manager
    )