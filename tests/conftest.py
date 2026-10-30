"""Test fixtures: the API wired to in-memory databases (no MySQL/MongoDB needed).

SQL routes use SQLite in-memory; Mongo routes use mongomock. The `api`
fixture is parametrized so every API test runs against both backends.
"""
import mongomock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.common.columns import GENERATION_SOURCES
from src.db.mongo import ensure_indexes, get_readings_collection
from src.db.sql import Base, GenerationSource, get_session, make_session_factory


@pytest.fixture
def sql_session_factory():
    # StaticPool: one shared connection, otherwise each one gets an empty in-memory DB
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")  # SQLite has them off by default

    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        session.add_all([GenerationSource(name=n, category=c) for n, c in GENERATION_SOURCES.items()])
        session.commit()
    yield factory
    engine.dispose()


@pytest.fixture
def mongo_collection():
    coll = mongomock.MongoClient(tz_aware=True)["test"]["energy_readings"]
    ensure_indexes(coll)
    return coll


@pytest.fixture
def client(sql_session_factory, mongo_collection):
    def _session():
        with sql_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_readings_collection] = lambda: mongo_collection
    # Not used as a context manager, so the startup hook never touches real MongoDB
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(params=["/sql", "/mongo"])
def api(request, client):
    """(client, prefix) for each backend."""
    return client, request.param


def make_reading(timestamp="2019-01-01T00:00:00Z", price=50.0, **overrides):
    reading = {
        "timestamp": timestamp,
        "total_load_actual": 25000.0,
        "total_load_forecast": 25100.0,
        "price_actual": price,
        "price_day_ahead": 48.0,
        "forecast_solar_day_ahead": 100.0,
        "forecast_wind_onshore_day_ahead": 5000.0,
        "generation": {name: 10.0 for name in GENERATION_SOURCES},
    }
    reading.update(overrides)
    return reading
