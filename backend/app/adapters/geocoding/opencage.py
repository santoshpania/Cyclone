"""OpenCage forward geocoding. Its terms allow storing results permanently."""

from __future__ import annotations

import httpx

from app.adapters.geocoding.base import GeocodeResult, Precision

_TYPE_PRECISION: dict[str, Precision] = {
    "building": "rooftop",
    "house": "rooftop",
    "poi": "rooftop",
    "road": "street",
    "street": "street",
    "neighbourhood": "neighbourhood",
    "suburb": "neighbourhood",
    "quarter": "neighbourhood",
    "city": "locality",
    "town": "locality",
    "village": "locality",
    "county": "region",
    "state": "region",
    "state_district": "region",
    "country": "region",
}


class OpenCageGeocoder:
    provider = "opencage"
    sku = "opencage_request"
    url = "https://api.opencagedata.com/geocode/v1/json"

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None):
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=10)

    async def geocode(self, query: str, *, country_codes: str) -> GeocodeResult | None:
        resp = await self._client.get(
            self.url,
            params={
                "q": query,
                "key": self._key,
                "countrycode": country_codes,
                "limit": 1,
                "no_annotations": 1,
                "no_record": 1,
            },
        )
        if resp.status_code in (402, 403, 429):
            resp.raise_for_status()
        if resp.status_code != 200:
            return None
        results = resp.json().get("results") or []
        if not results:
            return None
        r = results[0]
        kind = str((r.get("components") or {}).get("_type", ""))
        return GeocodeResult(
            lat=float(r["geometry"]["lat"]),
            lng=float(r["geometry"]["lng"]),
            precision=_TYPE_PRECISION.get(kind, "unknown"),
            confidence=min(1.0, float(r.get("confidence", 0)) / 10),
            provider=self.provider,
            storable_until=None,
        )
