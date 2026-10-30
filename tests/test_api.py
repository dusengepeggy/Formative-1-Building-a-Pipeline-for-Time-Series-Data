"""API tests. Each test using `api` runs once for /sql and once for /mongo."""
import pytest

from tests.conftest import make_reading

TS = "2019-01-01T00:00:00Z"


def hours(n, start_day="2019-01-01"):
    return [f"{start_day}T{h:02d}:00:00Z" for h in range(n)]


# --- create / read ---------------------------------------------------------

def test_create_and_get(api):
    client, prefix = api
    body = make_reading(TS)
    created = client.post(f"{prefix}/readings", json=body)
    assert created.status_code == 201
    assert created.json() == body

    fetched = client.get(f"{prefix}/readings/{TS}")
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_create_duplicate_returns_409(api):
    client, prefix = api
    assert client.post(f"{prefix}/readings", json=make_reading(TS)).status_code == 201
    assert client.post(f"{prefix}/readings", json=make_reading(TS)).status_code == 409


def test_timestamp_without_offset_is_utc(api):
    client, prefix = api
    client.post(f"{prefix}/readings", json=make_reading("2019-01-01T05:00:00"))
    res = client.get(f"{prefix}/readings/2019-01-01T05:00:00Z")
    assert res.status_code == 200
    assert res.json()["timestamp"] == "2019-01-01T05:00:00Z"


def test_timestamp_with_offset_is_converted_to_utc(api):
    client, prefix = api
    client.post(f"{prefix}/readings", json=make_reading("2019-01-01T01:00:00+01:00"))
    assert client.get(f"{prefix}/readings/{TS}").json()["timestamp"] == TS


@pytest.mark.parametrize("bad", [
    {"total_load_forecast": -1.0},                      # negative load
    {"timestamp": "2019-01-01T00:30:00Z"},              # not on the hour
    {"generation": {"solar": 1.0}},                     # missing sources
    {"generation": {**make_reading()["generation"], "unicorn": 1.0}},  # unknown source
    {"colour": "blue"},                                 # unknown field
])
def test_create_invalid_returns_422(api, bad):
    client, prefix = api
    assert client.post(f"{prefix}/readings", json=make_reading(**bad)).status_code == 422


def test_get_missing_returns_404(api):
    client, prefix = api
    assert client.get(f"{prefix}/readings/{TS}").status_code == 404


def test_null_total_load_actual_allowed(api):
    client, prefix = api
    res = client.post(f"{prefix}/readings", json=make_reading(TS, total_load_actual=None))
    assert res.status_code == 201
    assert res.json()["total_load_actual"] is None


# --- update ------------------------------------------------------------------

def test_partial_update(api):
    client, prefix = api
    client.post(f"{prefix}/readings", json=make_reading(TS))
    res = client.put(f"{prefix}/readings/{TS}",
                     json={"price_actual": 99.5, "generation": {"solar": 123.0}})
    assert res.status_code == 200

    expected = make_reading(TS)
    expected["price_actual"] = 99.5
    expected["generation"]["solar"] = 123.0
    assert res.json() == expected
    assert client.get(f"{prefix}/readings/{TS}").json() == expected


def test_full_update(api):
    client, prefix = api
    client.post(f"{prefix}/readings", json=make_reading(TS))
    new = make_reading(TS, price=10.0, price_day_ahead=11.0)
    new["generation"] = {name: 1.0 for name in new["generation"]}
    body = {k: v for k, v in new.items() if k != "timestamp"}
    assert client.put(f"{prefix}/readings/{TS}", json=body).json() == new


def test_update_missing_returns_404(api):
    client, prefix = api
    assert client.put(f"{prefix}/readings/{TS}", json={"price_actual": 1.0}).status_code == 404


def test_update_null_required_field_returns_422(api):
    client, prefix = api
    client.post(f"{prefix}/readings", json=make_reading(TS))
    assert client.put(f"{prefix}/readings/{TS}", json={"price_actual": None}).status_code == 422


# --- delete ------------------------------------------------------------------

def test_delete(api):
    client, prefix = api
    client.post(f"{prefix}/readings", json=make_reading(TS))
    res = client.delete(f"{prefix}/readings/{TS}")
    assert res.status_code == 200
    assert res.json()["timestamp"] == TS
    assert client.get(f"{prefix}/readings/{TS}").status_code == 404
    assert client.delete(f"{prefix}/readings/{TS}").status_code == 404


def test_delete_then_recreate(api):
    # Proves generation rows/fields were removed with the reading (no PK clash)
    client, prefix = api
    client.post(f"{prefix}/readings", json=make_reading(TS))
    client.delete(f"{prefix}/readings/{TS}")
    assert client.post(f"{prefix}/readings", json=make_reading(TS)).status_code == 201


# --- latest / range / list ---------------------------------------------------

def test_latest(api):
    client, prefix = api
    assert client.get(f"{prefix}/readings/latest").status_code == 404
    for ts in ["2019-01-01T02:00:00Z", "2019-01-01T05:00:00Z", "2019-01-01T01:00:00Z"]:
        client.post(f"{prefix}/readings", json=make_reading(ts))
    assert client.get(f"{prefix}/readings/latest").json()["timestamp"] == "2019-01-01T05:00:00Z"


def test_range_is_inclusive_and_sorted(api):
    client, prefix = api
    ts = hours(6)
    for t in reversed(ts):
        client.post(f"{prefix}/readings", json=make_reading(t))
    res = client.get(f"{prefix}/readings/range", params={"start": ts[1], "end": ts[3]})
    assert res.status_code == 200
    assert [r["timestamp"] for r in res.json()] == ts[1:4]


def test_range_limit_and_offset(api):
    client, prefix = api
    ts = hours(6)
    for t in ts:
        client.post(f"{prefix}/readings", json=make_reading(t))
    res = client.get(f"{prefix}/readings/range",
                     params={"start": ts[0], "end": ts[5], "limit": 2, "offset": 3})
    assert [r["timestamp"] for r in res.json()] == ts[3:5]


@pytest.mark.parametrize("params", [
    {"start": "2019-01-02T00:00:00Z", "end": "2019-01-01T00:00:00Z"},           # start > end
    {"start": "2019-01-01T00:00:00Z", "end": "2019-01-02T00:00:00Z", "limit": 100000},  # over cap
    {"start": "not-a-date", "end": "2019-01-02T00:00:00Z"},
    {"end": "2019-01-02T00:00:00Z"},                                             # missing start
])
def test_range_invalid_returns_422(api, params):
    client, prefix = api
    assert client.get(f"{prefix}/readings/range", params=params).status_code == 422


def test_list_pagination(api):
    client, prefix = api
    ts = hours(5)
    for t in ts:
        client.post(f"{prefix}/readings", json=make_reading(t))
    res = client.get(f"{prefix}/readings", params={"limit": 2, "offset": 1})
    assert res.status_code == 200
    assert [r["timestamp"] for r in res.json()] == ts[1:3]


# --- cross-backend -----------------------------------------------------------

def test_both_backends_return_same_shape(client):
    body = make_reading(TS, total_load_actual=None)
    for prefix in ("/sql", "/mongo"):
        client.post(f"{prefix}/readings", json=body)
    assert client.get(f"/sql/readings/{TS}").json() == client.get(f"/mongo/readings/{TS}").json()


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "mysql": "ok", "mongo": "ok"}
