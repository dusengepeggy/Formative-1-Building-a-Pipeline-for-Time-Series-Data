"""Request/response models shared by the /sql and /mongo routers.

Both databases return the same JSON shape. Timestamps are ISO 8601 in UTC
(responses end in "Z"); a timestamp sent without an offset is taken as UTC.
"""
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.common.columns import GENERATION_SOURCES


def to_utc(ts: datetime) -> datetime:
    """Aware UTC datetime; naive input is assumed to be UTC already."""
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def _check_generation(gen: dict[str, float], require_all: bool) -> dict[str, float]:
    unknown = set(gen) - set(GENERATION_SOURCES)
    if unknown:
        raise ValueError(f"unknown generation sources: {sorted(unknown)}")
    missing = set(GENERATION_SOURCES) - set(gen)
    if require_all and missing:
        raise ValueError(f"missing generation sources: {sorted(missing)}")
    if any(v < 0 for v in gen.values()):
        raise ValueError("generation values must be >= 0")
    return gen


class ReadingCreate(BaseModel):
    # Reject unknown fields and NaN/inf so typos fail loudly instead of being dropped
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    timestamp: datetime
    total_load_actual: float | None = Field(None, ge=0)
    total_load_forecast: float = Field(ge=0)
    price_actual: float  # EUR/MWh; can be negative in power markets
    price_day_ahead: float
    forecast_solar_day_ahead: float = Field(ge=0)
    forecast_wind_onshore_day_ahead: float = Field(ge=0)
    generation: dict[str, float] = Field(description="MW per source; all sources required")

    @field_validator("timestamp")
    @classmethod
    def _hourly_utc(cls, ts: datetime) -> datetime:
        ts = to_utc(ts)
        # The dataset (and the model's lags) are hourly
        if (ts.minute, ts.second, ts.microsecond) != (0, 0, 0):
            raise ValueError("timestamp must be on the hour")
        return ts

    @field_validator("generation")
    @classmethod
    def _full_generation(cls, gen):
        return _check_generation(gen, require_all=True)


class ReadingUpdate(BaseModel):
    """Full or partial update: only the fields sent are changed."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    total_load_actual: float | None = Field(None, ge=0)
    total_load_forecast: float | None = Field(None, ge=0)
    price_actual: float | None = None
    price_day_ahead: float | None = None
    forecast_solar_day_ahead: float | None = Field(None, ge=0)
    forecast_wind_onshore_day_ahead: float | None = Field(None, ge=0)
    generation: dict[str, float] | None = Field(None, description="subset of sources to change")

    @field_validator("generation")
    @classmethod
    def _partial_generation(cls, gen):
        return gen if gen is None else _check_generation(gen, require_all=False)

    @model_validator(mode="after")
    def _no_null_required(self):
        # Only total_load_actual may be null (as in the data); others are NOT NULL
        nulls = [f for f in self.model_fields_set
                 if f != "total_load_actual" and getattr(self, f) is None]
        if nulls:
            raise ValueError(f"fields cannot be null: {sorted(nulls)}")
        return self


class ReadingOut(BaseModel):
    timestamp: datetime
    total_load_actual: float | None
    total_load_forecast: float
    price_actual: float
    price_day_ahead: float
    forecast_solar_day_ahead: float
    forecast_wind_onshore_day_ahead: float
    generation: dict[str, float]

    @field_validator("timestamp")
    @classmethod
    def _utc(cls, ts: datetime) -> datetime:
        return to_utc(ts)
