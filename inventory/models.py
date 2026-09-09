from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField(unique=True)
    dummyjson_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    image_url = models.URLField(blank=True)

    class Meta:
        db_table = "clinic_users"
        ordering = ["username"]

    def __str__(self) -> str:
        return self.username


class LoginEvent(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="login_events"
    )
    username = models.CharField(max_length=150)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "clinic_login_events"
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"{self.username} at {self.occurred_at.isoformat()}"
