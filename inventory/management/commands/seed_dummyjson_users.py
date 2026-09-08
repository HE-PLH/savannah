from typing import Any

from django.core.management.base import BaseCommand, CommandError

from inventory.models import User
from inventory.upstream import UpstreamError, client


class Command(BaseCommand):
    help = "Create or update local users from DummyJSON"

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            payload = client.request("GET", "/users", params={"limit": 0})
        except UpstreamError as exc:
            raise CommandError(exc.message) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("users"), list):
            raise CommandError("DummyJSON returned an invalid users response")

        created = 0
        updated = 0
        for source in payload["users"]:
            if not isinstance(source, dict):
                continue
            required = ("id", "username", "email", "password")
            if any(not source.get(field) for field in required):
                continue
            user, was_created = User.objects.update_or_create(
                dummyjson_id=int(source["id"]),
                defaults={
                    "username": str(source["username"]),
                    "email": str(source["email"]).lower(),
                    "first_name": str(source.get("firstName", "")),
                    "last_name": str(source.get("lastName", "")),
                    "image_url": str(source.get("image", "")),
                    "is_active": True,
                },
            )
            user.set_password(str(source["password"]))
            user.save(update_fields=["password"])
            created += int(was_created)
            updated += int(not was_created)

        self.stdout.write(self.style.SUCCESS(f"Seeded {created} new and {updated} existing users"))
