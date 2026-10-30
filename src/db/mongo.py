"""MongoDB client from env and conversion between API readings and documents.

Design rationale: database/mongo/design.md.
"""
import os
from datetime import timezone
from functools import lru_cache

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient

load_dotenv()

COLLECTION = "energy_readings"


# API field -> dotted document path, used for partial updates ($set)
FIELD_PATHS = {
    "total_load_actual": "load.actual",
    "total_load_forecast": "load.forecast",
    "price_actual": "price.actual",
    "price_day_ahead": "price.day_ahead",
    "forecast_solar_day_ahead": "forecasts.solar_day_ahead",
    "forecast_wind_onshore_day_ahead": "forecasts.wind_onshore_day_ahead",
}


def get_client(url=None):
    # tz_aware=True returns datetimes tagged as UTC instead of naive ones;
    # a short server-selection timeout makes an unreachable server fail fast
    return MongoClient(url or os.environ["MONGO_URL"], tz_aware=True,
                       serverSelectionTimeoutMS=5000)


def get_collection(client, db_name=None):
    return client[db_name or os.environ.get("MONGO_DB", "energy")][COLLECTION]


@lru_cache
def _default_client():
    # One client per process: MongoClient pools connections and is thread-safe
    return get_client()


def get_readings_collection():
    """FastAPI dependency returning the energy_readings collection."""
    return get_collection(_default_client())


def ensure_indexes(coll):
    # Unique: one document per hour; also serves lookups, ranges and "latest"
    coll.create_index([("timestamp", ASCENDING)], unique=True, name="uq_timestamp")
    # Highest-price-hours queries sort on this field
    coll.create_index([("price.actual", DESCENDING)], name="idx_price_actual")


def reading_to_document(reading):
    """API-shaped reading dict -> MongoDB document."""
    ts = reading["timestamp"].astimezone(timezone.utc)
    return {
        "timestamp": ts,
        "load": {"actual": reading["total_load_actual"],
                 "forecast": reading["total_load_forecast"]},
        "price": {"actual": reading["price_actual"],
                  "day_ahead": reading["price_day_ahead"]},
        "forecasts": {"solar_day_ahead": reading["forecast_solar_day_ahead"],
                      "wind_onshore_day_ahead": reading["forecast_wind_onshore_day_ahead"]},
        "generation": dict(reading["generation"]),
        # UTC parts (dayofweek 0 = Monday) so grouping needs no date maths
        "date_parts": {"year": ts.year, "month": ts.month,
                       "dayofweek": ts.weekday(), "hour": ts.hour},
    }


def document_to_reading(doc):
    """MongoDB document -> API-shaped reading dict."""
    return {
        "timestamp": doc["timestamp"],
        "total_load_actual": doc["load"]["actual"],
        "total_load_forecast": doc["load"]["forecast"],
        "price_actual": doc["price"]["actual"],
        "price_day_ahead": doc["price"]["day_ahead"],
        "forecast_solar_day_ahead": doc["forecasts"]["solar_day_ahead"],
        "forecast_wind_onshore_day_ahead": doc["forecasts"]["wind_onshore_day_ahead"],
        "generation": doc["generation"],
    }
