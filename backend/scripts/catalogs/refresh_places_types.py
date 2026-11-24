"""Refresh app/catalogs/places_types.json from Google's Places API (New) "Table A" type list.

The Phase 2 profile validator only accepts `includedType` values from this file.
Google publishes the list as a docs page, not an API, so this parses that page and FAILS
LOUDLY if the structure changed — re-check the output by hand before committing.

    uv run python scripts/catalogs/refresh_places_types.py
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx

URL = "https://developers.google.com/maps/documentation/places/web-service/place-types"
OUT = Path(__file__).resolve().parents[2] / "app" / "catalogs" / "places_types.json"


def main() -> None:
    html = httpx.get(URL, timeout=60, follow_redirects=True).text
    table_a = html.split('id="table-a"', 1)
    if len(table_a) != 2:
        raise SystemExit("could not find Table A on the page; the docs layout changed")
    section = table_a[1].split('id="table-b"', 1)[0]
    types = sorted(set(re.findall(r"<code[^>]*>([a-z][a-z0-9_]+)</code>", section)))
    if len(types) < 100:
        raise SystemExit(f"only {len(types)} types parsed; refusing to write a partial catalog")
    OUT.write_text(
        json.dumps({"_source": URL, "_fetched_at": datetime.now(UTC).isoformat(), "table_a": types}, indent=1)
        + "\n"
    )
    print(f"wrote {len(types)} types to {OUT}")


if __name__ == "__main__":
    main()
