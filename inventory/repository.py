from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError


class StockRepository:
    def __init__(self) -> None:
        self._client: MongoClient[dict[str, Any]] | None = None

    @property
    def collection(self) -> Collection[dict[str, Any]]:
        if self._client is None:
            self._client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=1500)
        return self._client[settings.MONGODB_DATABASE]["stock_overrides"]

    def stocks_for(self, product_ids: list[int], clinic_id: str = "default") -> dict[int, int]:
        if not product_ids:
            return {}
        try:
            rows = self.collection.find(
                {"clinic_id": clinic_id, "product_id": {"$in": product_ids}},
                {"product_id": 1, "stock": 1},
            )
            return {int(row["product_id"]): int(row["stock"]) for row in rows}
        except PyMongoError:
            return {}

    def save(self, product_id: int, stock: int, clinic_id: str = "default") -> None:
        try:
            self.collection.update_one(
                {"clinic_id": clinic_id, "product_id": product_id},
                {
                    "$set": {"stock": stock, "updated_at": datetime.now(UTC)},
                    "$setOnInsert": {"created_at": datetime.now(UTC)},
                },
                upsert=True,
            )
        except PyMongoError as exc:
            raise RuntimeError("Stock correction could not be persisted") from exc


repository = StockRepository()
