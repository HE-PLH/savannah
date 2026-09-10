from io import StringIO
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from django.core.management import call_command
from django.test import Client

from inventory.models import LoginEvent, User
from inventory.upstream import DummyJsonClient, UpstreamError


@pytest.fixture(autouse=True)
def disable_ssl_redirect(settings: Any) -> None:
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture
def user(db: None) -> User:
    return User.objects.create_user(
        username="ward.user",
        email="ward.user@example.com",
        password="physical-count-pass",
        first_name="Ward",
        last_name="User",
    )


@pytest.fixture
def browser(user: User) -> Client:
    client = Client(enforce_csrf_checks=False)
    client.force_login(user, backend="inventory.backends.EmailOrUsernameBackend")
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("identifier", ["ward.user", "WARD.USER@EXAMPLE.COM"])
def test_login_accepts_username_or_email(identifier: str, user: User) -> None:
    client = Client(enforce_csrf_checks=False)

    response = client.post(
        "/api/auth/login",
        {
            "username": identifier,
            "password": "physical-count-pass",
            "expiresInMins": 1,
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["username"] == "ward.user"
    assert 0 < client.session.get_expiry_age() <= 60
    assert client.get("/api/auth/me").json()["email"] == "ward.user@example.com"
    event = LoginEvent.objects.get(user=user)
    assert event.username == "ward.user"
    assert event.ip_address == "127.0.0.1"
    assert event.occurred_at is not None


@pytest.mark.django_db
def test_invalid_login_does_not_create_a_session(user: User) -> None:
    client = Client(enforce_csrf_checks=False)

    response = client.post(
        "/api/auth/login",
        {"username": user.email, "password": "wrong"},
        content_type="application/json",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert client.get("/api/auth/me").status_code == 401
    assert not LoginEvent.objects.exists()


@pytest.mark.django_db
def test_logout_revokes_the_session(browser: Client) -> None:
    assert browser.post("/api/auth/logout").status_code == 204
    assert browser.get("/api/auth/me").status_code == 401


@pytest.mark.django_db
def test_catalogue_requires_a_session() -> None:
    response = Client().get("/api/products")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_azure_app_service_hostname_is_allowed() -> None:
    response = Client().get(
        "/",
        HTTP_HOST="savannah-g3fjc3g7hjfgf7c2.austriaeast-01.azurewebsites.net",
        HTTP_X_FORWARDED_PROTO="https",
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "savannah-backend"}
    assert response.wsgi_request.is_secure()


def test_upstream_500_is_normalized_and_recoverable(browser: Client) -> None:
    with patch("inventory.views.client.request", side_effect=UpstreamError(500, "failed")):
        response = browser.get("/api/products")

    assert response.status_code == 502
    assert response.json() == {"error": {"code": "upstream_error", "message": "failed"}}


def test_dummyjson_http_500_path_raises_upstream_error() -> None:
    response = httpx.Response(500, json={"message": "Internal Server Error"})
    with (
        patch("inventory.upstream.httpx.request", return_value=response) as request,
        pytest.raises(UpstreamError) as raised,
    ):
        DummyJsonClient().request("GET", "/http/500")

    assert raised.value.status == 500
    assert raised.value.message == "Internal Server Error"
    assert request.call_args.args[1].endswith("/http/500")


def test_stock_update_persists_override_and_returns_it(browser: Client) -> None:
    with (
        patch(
            "inventory.views.client.request", return_value={"id": 7, "title": "Item", "stock": 3}
        ),
        patch("inventory.views.repository.save") as save,
    ):
        response = browser.put("/api/products/7", {"stock": 19}, content_type="application/json")

    assert response.status_code == 200
    assert response.json()["stock"] == 19
    save.assert_called_once_with(7, 19)


def test_bulk_corrections_reports_partial_results(browser: Client) -> None:
    with (
        patch(
            "inventory.views.client.request",
            side_effect=[{"id": 7, "stock": 3}, UpstreamError(500, "failed")],
        ),
        patch("inventory.views.repository.save") as save,
    ):
        response = browser.post(
            "/api/products/bulk-corrections",
            {
                "corrections": [
                    {"productId": 7, "stock": 19},
                    {"productId": 8, "stock": 21},
                    {"productId": 9, "stock": -1},
                ]
            },
            content_type="application/json",
        )

    assert response.status_code == 200
    assert response.json()["summary"] == {"total": 3, "succeeded": 1, "failed": 2}
    assert [result["status"] for result in response.json()["results"]] == [
        "success",
        "failure",
        "failure",
    ]
    save.assert_called_once_with(7, 19)


def test_bulk_corrections_requires_a_session() -> None:
    response = Client().post(
        "/api/products/bulk-corrections",
        {"corrections": [{"productId": 7, "stock": 19}]},
        content_type="application/json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_seed_command_hashes_dummyjson_passwords() -> None:
    payload = {
        "users": [
            {
                "id": 1,
                "username": "emilys",
                "email": "emily@example.com",
                "password": "emilyspass",
                "firstName": "Emily",
                "lastName": "Johnson",
                "image": "https://example.com/emily.png",
            }
        ]
    }
    with patch(
        "inventory.management.commands.seed_dummyjson_users.client.request", return_value=payload
    ):
        call_command("seed_dummyjson_users", stdout=StringIO())

    seeded = User.objects.get(username="emilys")
    assert seeded.password != "emilyspass"
    assert seeded.check_password("emilyspass")
    assert seeded.dummyjson_id == 1
