from django.db import models
from django.contrib.auth.models import User

class ActivityLog(models.Model):
    user=models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )
    action=models.CharField(max_length=200)
    ip_address=models.GenericIPAddressField()
    user_agent=models.TextField()
    created_on=models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.action}"
