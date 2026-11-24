"""Geocoder interface. Results carry precision and storage terms (CLAUDE.md data terms)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

Precision = Literal["rooftop", "street", "neighbourhood", "locality", "region", "unknown", "source"]
PRECISION_RANK: dict[Precision, int] = {
    "source": 5,
    "rooftop": 5,
    "street": 4,
    "neighbourhood": 3,
    "locality": 2,
    "region": 1,
    "unknown": 0,
}


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lng: float
    precision: Precision
    confidence: float  # 0–1
    provider: str
    storable_until: datetime | None  # None = provider terms allow permanent storage

    def as_json(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "precision": self.precision,
            "confidence": round(self.confidence, 2),
            "storable_until": self.storable_until.isoformat() if self.storable_until else None,
        }


class Geocoder(Protocol):
    provider: str
    sku: str  # pricing.yaml key under `geocoder`

    async def geocode(self, query: str, *, country_codes: str) -> GeocodeResult | None: ...
