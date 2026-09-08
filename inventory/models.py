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
