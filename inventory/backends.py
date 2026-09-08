from typing import Any

from django.contrib.auth.backends import BaseBackend
from django.http import HttpRequest

from .models import User


class EmailOrUsernameBackend(BaseBackend):
    def authenticate(
        self,
        request: HttpRequest | None,
        **kwargs: Any,
    ) -> User | None:
        identifier = kwargs.get("username") or kwargs.get("email")
        password = kwargs.get("password")
        if not isinstance(identifier, str) or not password:
            return None
        try:
            user = User.objects.get(email__iexact=identifier)
        except User.DoesNotExist:
            try:
                user = User.objects.get(username__iexact=identifier)
            except User.DoesNotExist:
                User().set_password(password)
                return None
        if not isinstance(password, str):
            return None
        return user if user.check_password(password) and user.is_active else None

    def get_user(self, user_id: Any) -> User | None:
        try:
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, TypeError, ValueError):
            return None
        return user if user.is_active else None
