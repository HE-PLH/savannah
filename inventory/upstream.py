from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings


class UpstreamError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


class DummyJsonClient:
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        query = dict(params or {})
        if settings.DUMMYJSON_DELAY_MS:
            query["delay"] = settings.DUMMYJSON_DELAY_MS
        try:
            response = httpx.request(
                method,
                f"{settings.DUMMYJSON_BASE_URL}{path}",
                params=query,
                json=json,
                timeout=10,
            )
        except httpx.RequestError as exc:
            raise UpstreamError(503, "Catalogue service is unavailable") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", "Catalogue request failed")
            except (ValueError, AttributeError):
                detail = "Catalogue request failed"
            raise UpstreamError(response.status_code, str(detail))
        result = response.json()
        if not isinstance(result, dict | list):
            raise UpstreamError(502, "Catalogue returned an invalid response")
        return result


client = DummyJsonClient()
