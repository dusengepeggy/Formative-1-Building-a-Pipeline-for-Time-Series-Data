"""Smoke test every endpoint of a running API against the real databases.

Usage (repo root, API running via `uvicorn src.api.main:app`):
    python scripts/smoke_test_api.py [--api-url http://127.0.0.1:8000]

Creates a reading at 2019-01-01T00:00:00Z (after the dataset ends), updates
and deletes it, so the databases end up unchanged. Exits 1 if any check fails.
"""
import argparse
import os
import sys

import requests
from dotenv import load_dotenv

TEST_TS = "2019-01-01T00:00:00Z"
LAST_TS = "2018-12-31T22:00:00Z"  # last hour in the dataset


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Smoke test the running API")
    parser.add_argument("--api-url", default=os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"))
    base = parser.parse_args().api_url.rstrip("/")
    failures = 0

    def check(method, path, expected, **kwargs):
        nonlocal failures
        res = requests.request(method, base + path, timeout=30, **kwargs)
        ok = res.status_code == expected
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {method:6} {path:60} -> {res.status_code} (expected {expected})")
        return res

    health = check("GET", "/health", 200)
    print(f"      {health.json()}")

    for prefix in ("/sql", "/mongo"):
        print(f"\n== {prefix}")
        check("GET", f"{prefix}/readings", 200, params={"limit": 2})
        latest = check("GET", f"{prefix}/readings/latest", 200).json()
        print(f"      latest timestamp: {latest['timestamp']}, price_actual: {latest['price_actual']}")
        rng = check("GET", f"{prefix}/readings/range", 200,
                    params={"start": "2018-12-31T20:00:00Z", "end": LAST_TS}).json()
        print(f"      range 20:00-22:00 returned {len(rng)} readings")
        check("GET", f"{prefix}/readings/range", 422,
              params={"start": LAST_TS, "end": "2018-12-31T20:00:00Z"})
        check("GET", f"{prefix}/readings/{LAST_TS}", 200)

        new = {**latest, "timestamp": TEST_TS}
        check("POST", f"{prefix}/readings", 201, json=new)
        check("POST", f"{prefix}/readings", 409, json=new)
        updated = check("PUT", f"{prefix}/readings/{TEST_TS}", 200,
                        json={"price_actual": 1.23, "generation": {"solar": 0.0}}).json()
        print(f"      after PUT: price_actual={updated['price_actual']}, "
              f"solar={updated['generation']['solar']}")
        check("GET", f"{prefix}/readings/latest", 200)
        check("DELETE", f"{prefix}/readings/{TEST_TS}", 200)
        check("GET", f"{prefix}/readings/{TEST_TS}", 404)
        check("PUT", f"{prefix}/readings/{TEST_TS}", 404, json={"price_actual": 1.0})
        check("DELETE", f"{prefix}/readings/{TEST_TS}", 404)
        after = check("GET", f"{prefix}/readings/latest", 200).json()
        print(f"      latest after cleanup: {after['timestamp']}")

    print(f"\n{'All checks passed' if not failures else f'{failures} check(s) FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
