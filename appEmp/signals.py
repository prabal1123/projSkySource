# from django.db.models.signals import post_save
# from django.dispatch import receiver
# from django.contrib.auth.models import User
# from .models import empProfile

# @receiver(post_save,sender=User)
# def create_profile(sender,instance,created,**kwargs):
#     if created:
#         empProfile.objects.create(user=instance)

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import empProfile

@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        role = 'SUPER_ADMIN' if instance.is_superuser else 'EMPLOYEE'
        empProfile.objects.create(user=instance, role=role)