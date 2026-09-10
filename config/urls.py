from django.contrib import admin
from django.http import HttpRequest, JsonResponse
from django.urls import include, path


def health(_: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "service": "savannah-backend"})


urlpatterns = [
    path("", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/", include("inventory.urls")),
]
