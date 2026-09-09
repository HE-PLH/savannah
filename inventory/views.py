from __future__ import annotations

from typing import Any

from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .models import LoginEvent, User
from .repository import repository
from .upstream import UpstreamError, client

SORT_FIELDS = {"title", "price", "rating", "stock", "category", "brand"}


def error_response(code: str, message: str, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def current_user(request: Request) -> User | None:
    user = request.user
    return user if isinstance(user, User) and user.is_authenticated else None


def user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.pk,
        "username": user.username,
        "email": user.email,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "image": user.image_url,
    }


def authentication_required(request: Request) -> Response | None:
    if current_user(request) is None:
        return error_response("authentication_required", "Sign in is required", 401)
    return None


def catalogue_request(method: str, path: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
    return client.request(method, path, **kwargs)


def upstream_error(exc: UpstreamError) -> Response:
    status = exc.status if 400 <= exc.status < 500 else 502
    return error_response("upstream_error", exc.message, status)


def overlay_stocks(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stocks = repository.stocks_for([int(product["id"]) for product in products])
    return [
        {**product, "stock": stocks.get(int(product["id"]), product.get("stock", 0))}
        for product in products
    ]


@ensure_csrf_cookie
@api_view(["GET"])
def csrf_token(request: HttpRequest) -> Response:
    return Response({"csrfToken": get_token(request)})


@csrf_protect
@api_view(["POST"])
def login(request: Request) -> Response:
    identifier = request.data.get("username")
    password = request.data.get("password")
    expires_in_mins = request.data.get("expiresInMins")
    if (
        not isinstance(identifier, str)
        or not isinstance(password, str)
        or not identifier.strip()
        or not password
    ):
        return error_response(
            "invalid_credentials", "Email or username and password are required", 400
        )
    user = authenticate(request._request, username=identifier.strip(), password=password)
    if not isinstance(user, User):
        return error_response(
            "invalid_credentials", "Email, username, or password is incorrect", 401
        )
    django_login(request._request, user)
    if isinstance(expires_in_mins, int) and not isinstance(expires_in_mins, bool):
        request._request.session.set_expiry(max(1, expires_in_mins) * 60)
    LoginEvent.objects.create(
        user=user,
        username=user.username,
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
    )
    return Response(user_payload(user))


@ensure_csrf_cookie
@api_view(["GET"])
def me(request: Request) -> Response:
    user = current_user(request)
    if user is None:
        return error_response("authentication_required", "Sign in is required", 401)
    return Response(user_payload(user))


@csrf_protect
@api_view(["POST"])
def refresh(request: Request) -> Response:
    if current_user(request) is None:
        return error_response("session_expired", "Your session has ended", 401)
    request._request.session.set_expiry(None)
    return Response({"ok": True})


@csrf_protect
@api_view(["POST"])
def logout(request: Request) -> Response:
    django_logout(request._request)
    return Response(status=204)


@api_view(["GET"])
def categories(request: Request) -> Response:
    if denied := authentication_required(request):
        return denied
    try:
        return Response(catalogue_request("GET", "/products/categories"))
    except UpstreamError as exc:
        return upstream_error(exc)


@api_view(["GET"])
def products(request: Request) -> Response:
    if denied := authentication_required(request):
        return denied
    try:
        page = max(1, int(request.query_params.get("page", "1")))
        limit = min(200, max(1, int(request.query_params.get("limit", "12"))))
    except ValueError:
        return error_response("invalid_pagination", "Page and limit must be numbers", 400)
    query = request.query_params.get("q", "").strip()
    category = request.query_params.get("category", "").strip()
    sort_by = request.query_params.get("sortBy", "title")
    order = request.query_params.get("order", "asc")
    if sort_by not in SORT_FIELDS or order not in {"asc", "desc"}:
        return error_response("invalid_sort", "Unsupported sort selection", 400)

    skip = (page - 1) * limit
    if category:
        try:
            payload = catalogue_request(
                "GET", f"/products/category/{category}", params={"limit": 0}
            )
        except UpstreamError as exc:
            return upstream_error(exc)
        assert isinstance(payload, dict)
        rows = list(payload.get("products", []))
        if query:
            needle = query.casefold()
            rows = [row for row in rows if needle in str(row.get("title", "")).casefold()]
        rows.sort(
            key=lambda row: (row.get(sort_by) is None, row.get(sort_by)), reverse=order == "desc"
        )
        total = len(rows)
        selected = rows[skip : skip + limit]
        result = {
            "products": overlay_stocks(selected),
            "total": total,
            "skip": skip,
            "limit": limit,
        }
    else:
        path = "/products/search" if query else "/products"
        params: dict[str, Any] = {
            "limit": limit,
            "skip": skip,
            "sortBy": sort_by,
            "order": order,
            "select": "id,title,description,category,price,rating,stock,thumbnail,brand,sku",
        }
        if query:
            params["q"] = query
        try:
            payload = catalogue_request("GET", path, params=params)
        except UpstreamError as exc:
            return upstream_error(exc)
        assert isinstance(payload, dict)
        result = {**payload, "products": overlay_stocks(list(payload.get("products", [])))}
    return Response(result)


@csrf_protect
@api_view(["POST"])
def bulk_corrections(request: Request) -> Response:
    if denied := authentication_required(request):
        return denied
    corrections = request.data.get("corrections")
    if not isinstance(corrections, list) or not 1 <= len(corrections) <= 200:
        return error_response(
            "invalid_corrections", "Provide between 1 and 200 stock corrections", 400
        )

    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    for correction in corrections:
        product_id = correction.get("productId") if isinstance(correction, dict) else None
        stock = correction.get("stock") if isinstance(correction, dict) else None
        if (
            isinstance(product_id, bool)
            or not isinstance(product_id, int)
            or product_id <= 0
            or product_id in seen
            or isinstance(stock, bool)
            or not isinstance(stock, int)
            or not 0 <= stock <= 1_000_000
        ):
            results.append(
                {
                    "productId": product_id,
                    "stock": stock,
                    "status": "failure",
                    "error": {
                        "code": "invalid_correction",
                        "message": (
                            "Each product must appear once with a whole stock count "
                            "from 0 to 1,000,000"
                        ),
                    },
                }
            )
            continue
        seen.add(product_id)
        try:
            catalogue_request("PUT", f"/products/{product_id}", json={"stock": stock})
            repository.save(product_id, stock)
        except UpstreamError as exc:
            results.append(
                {
                    "productId": product_id,
                    "stock": stock,
                    "status": "failure",
                    "error": {"code": "upstream_error", "message": exc.message},
                }
            )
        except RuntimeError as exc:
            results.append(
                {
                    "productId": product_id,
                    "stock": stock,
                    "status": "failure",
                    "error": {"code": "persistence_error", "message": str(exc)},
                }
            )
        else:
            results.append(
                {
                    "productId": product_id,
                    "stock": stock,
                    "status": "success",
                    "error": None,
                }
            )

    succeeded = sum(result["status"] == "success" for result in results)
    return Response(
        {
            "results": results,
            "summary": {
                "total": len(results),
                "succeeded": succeeded,
                "failed": len(results) - succeeded,
            },
        }
    )


@csrf_protect
@api_view(["GET", "PUT"])
def product_detail(request: Request, product_id: int) -> Response:
    if denied := authentication_required(request):
        return denied
    if request.method == "GET":
        try:
            payload = catalogue_request("GET", f"/products/{product_id}")
        except UpstreamError as exc:
            return upstream_error(exc)
        assert isinstance(payload, dict)
        product = overlay_stocks([payload])[0]
        return Response(product)

    stock = request.data.get("stock")
    if isinstance(stock, bool) or not isinstance(stock, int) or not 0 <= stock <= 1_000_000:
        return error_response(
            "invalid_stock", "Stock must be a whole number from 0 to 1,000,000", 400
        )
    try:
        payload = catalogue_request("PUT", f"/products/{product_id}", json={"stock": stock})
    except UpstreamError as exc:
        return upstream_error(exc)
    assert isinstance(payload, dict)
    try:
        repository.save(product_id, stock)
    except RuntimeError as exc:
        return error_response("persistence_error", str(exc), 503)
    return Response({**payload, "stock": stock})
