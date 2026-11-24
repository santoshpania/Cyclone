"""Refresh app/catalogs/osm_taginfo.json: values with usage counts for POI-bearing OSM keys.

The Phase 2 profile validator uses it to reject unknown keys and warn on rare values.
Needs network access to taginfo.openstreetmap.org (not reachable from every environment).

    uv run python scripts/catalogs/refresh_taginfo.py [--min-count 50]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

KEYS = [
    "amenity",
    "shop",
    "office",
    "craft",
    "healthcare",
    "industrial",
    "tourism",
    "leisure",
    "man_made",
    "club",
    "emergency",
    "sport",
    "building",
    "landuse",
    "company",
]
API = "https://taginfo.openstreetmap.org/api/4/key/values"
OUT = Path(__file__).resolve().parents[2] / "app" / "catalogs" / "osm_taginfo.json"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--min-count", type=int, default=50)
    args = p.parse_args()
    keys: dict[str, dict[str, int]] = {}
    with httpx.Client(timeout=60, headers={"User-Agent": "cyclone-catalog-refresh"}) as c:
        for key in KEYS:
            values: dict[str, int] = {}
            page = 1
            while True:
                r = c.get(
                    API,
                    params={"key": key, "page": page, "rp": 999, "sortname": "count", "sortorder": "desc"},
                )
                r.raise_for_status()
                rows = r.json()["data"]
                values.update({row["value"]: row["count"] for row in rows if row["count"] >= args.min_count})
                if not rows or rows[-1]["count"] < args.min_count:
                    break
                page += 1
            keys[key] = values
            print(f"{key}: {len(values)} values")
    OUT.write_text(
        json.dumps(
            {
                "_source": API,
                "_fetched_at": datetime.now(UTC).isoformat(),
                "_min_count": args.min_count,
                "keys": keys,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n"
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
