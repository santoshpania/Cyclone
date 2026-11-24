"""Google Geocoding API — fallback only. Google terms restrict storing geocodes, so results
carry a 30-day `storable_until` and the purge job removes them afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.adapters.geocoding.base import GeocodeResult, Precision

_LOCATION_TYPE: dict[str, Precision] = {
    "ROOFTOP": "rooftop",
    "RANGE_INTERPOLATED": "street",
    "GEOMETRIC_CENTER": "neighbourhood",
    "APPROXIMATE": "locality",
}
STORAGE_TTL = timedelta(days=30)


class GoogleGeocoder:
    provider = "google_geocoding"
    sku = "google_geocode"
    url = "https://maps.googleapis.com/maps/api/geocode/json"

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None):
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=10)

    async def geocode(self, query: str, *, country_codes: str) -> GeocodeResult | None:
        components = "|".join(f"country:{c.strip().upper()}" for c in country_codes.split(",") if c.strip())
        resp = await self._client.get(
            self.url, params={"address": query, "components": components, "key": self._key}
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        if body.get("status") in {"OVER_QUERY_LIMIT", "REQUEST_DENIED"}:
            raise httpx.HTTPStatusError(body.get("status", ""), request=resp.request, response=resp)
        results = body.get("results") or []
        if not results:
            return None
        r = results[0]
        geom = r["geometry"]
        precision = _LOCATION_TYPE.get(str(geom.get("location_type")), "unknown")
        return GeocodeResult(
            lat=float(geom["location"]["lat"]),
            lng=float(geom["location"]["lng"]),
            precision=precision,
            confidence=0.5 if r.get("partial_match") else 0.9,
            provider=self.provider,
            storable_until=datetime.now(UTC) + STORAGE_TTL,
        )
