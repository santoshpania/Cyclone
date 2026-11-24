"""Metered geocoding with a primary provider and an optional fallback."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.adapters.geocoding.base import PRECISION_RANK, Geocoder, GeocodeResult
from app.services.usage_meter import UsageMeter
from app.settings import get_settings

_override: list[Geocoder] | None = None


def set_geocoders(geocoders: list[Geocoder] | None) -> None:
    """Test hook."""
    global _override
    _override = geocoders


def configured_geocoders() -> list[Geocoder]:
    if _override is not None:
        return _override
    s = get_settings()
    chain: list[Geocoder] = []
    if s.opencage_api_key:
        from app.adapters.geocoding.opencage import OpenCageGeocoder

        chain.append(OpenCageGeocoder(s.opencage_api_key.get_secret_value()))
    if s.google_maps_server_key:
        from app.adapters.geocoding.google import GoogleGeocoder

        chain.append(GoogleGeocoder(s.google_maps_server_key.get_secret_value()))
    return chain


@dataclass
class MeteredGeocoder:
    """Tries providers in order; falls back when a result is missing or coarser than `min_precision`.
    Caches by query for the lifetime of one import run."""

    meter: UsageMeter
    chain: list[Geocoder]
    country_codes: str
    min_precision: str = "street"
    _cache: dict[str, GeocodeResult | None] = field(default_factory=dict)
    calls: int = 0

    async def geocode(self, query: str) -> GeocodeResult | None:
        key = " ".join(query.lower().split())
        if key in self._cache:
            return self._cache[key]
        best: GeocodeResult | None = None
        for g in self.chain:
            await self.meter.reserve("geocoder", g.sku, 1)  # raises BudgetExceeded
            self.calls += 1
            try:
                r = await g.geocode(query, country_codes=self.country_codes)
            except Exception:
                r = None
            if r and (best is None or PRECISION_RANK[r.precision] > PRECISION_RANK[best.precision]):
                best = r
            if best and PRECISION_RANK[best.precision] >= PRECISION_RANK[self.min_precision]:  # type: ignore[index]
                break
        self._cache[key] = best
        return best
