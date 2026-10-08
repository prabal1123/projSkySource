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

class DemoRequest(models.Model):
    name = models.CharField(max_length=100)
    company = models.CharField(max_length=150)
    team_size = models.CharField(max_length=20)
    phone = models.CharField(max_length=20)
    email = models.EmailField(max_length=254, blank=True)
    message = models.TextField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.company} - {self.name}"