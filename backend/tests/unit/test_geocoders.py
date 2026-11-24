from datetime import UTC, datetime, timedelta

import httpx
import respx

from app.adapters.geocoding.google import GoogleGeocoder
from app.adapters.geocoding.opencage import OpenCageGeocoder


@respx.mock
async def test_opencage_parses_and_is_permanently_storable() -> None:
    route = respx.get(OpenCageGeocoder.url).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "geometry": {"lat": 25.26, "lng": 55.29},
                        "confidence": 9,
                        "components": {"_type": "road"},
                    }
                ]
            },
        )
    )
    r = await OpenCageGeocoder("k").geocode("Al Fahidi St, Dubai", country_codes="ae")
    assert r is not None
    assert (r.lat, r.lng, r.precision, r.storable_until) == (25.26, 55.29, "street", None)
    assert r.confidence == 0.9
    assert route.calls.last.request.url.params["countrycode"] == "ae"


@respx.mock
async def test_opencage_no_result() -> None:
    respx.get(OpenCageGeocoder.url).mock(return_value=httpx.Response(200, json={"results": []}))
    assert await OpenCageGeocoder("k").geocode("nowhere", country_codes="ae") is None


@respx.mock
async def test_google_results_expire_within_30_days() -> None:
    respx.get(GoogleGeocoder.url).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {"geometry": {"location": {"lat": 24.45, "lng": 54.38}, "location_type": "ROOFTOP"}}
                ],
            },
        )
    )
    r = await GoogleGeocoder("k").geocode("Corniche Rd, Abu Dhabi", country_codes="ae")
    assert r is not None and r.precision == "rooftop"
    assert r.storable_until is not None
    assert r.storable_until <= datetime.now(UTC) + timedelta(days=30)
