"""Mapping between API / database field names and the original dataset columns.

The databases and the API use snake_case names; build_features expects the
original Kaggle column names. Keeping the mapping in one place lets the
forecast script rebuild exactly the dataframe the pipeline was trained on.
"""
import math

import pandas as pd

# API field -> dataset column, for the per-hour (non-generation) values
READING_FIELDS = {
    "total_load_actual": "total load actual",
    "total_load_forecast": "total load forecast",
    "price_actual": "price actual",
    "price_day_ahead": "price day ahead",
    "forecast_solar_day_ahead": "forecast solar day ahead",
    "forecast_wind_onshore_day_ahead": "forecast wind onshore day ahead",
}

# Generation source -> category. These are the generation columns left after
# load_and_clean drops the all-empty and all-zero ones.
GENERATION_SOURCES = {
    "biomass": "renewable",
    "fossil_brown_coal_lignite": "fossil",
    "fossil_gas": "fossil",
    "fossil_hard_coal": "fossil",
    "fossil_oil": "fossil",
    # NOT generation: electricity consumed to pump water uphill for storage.
    # Kept as 'other' and excluded from generation totals in queries.
    "hydro_pumped_storage_consumption": "other",
    "hydro_run_of_river_and_poundage": "renewable",
    "hydro_water_reservoir": "renewable",
    "nuclear": "nuclear",
    "other": "other",
    "other_renewable": "renewable",
    "solar": "renewable",
    "waste": "other",
    "wind_onshore": "renewable",
}

# Source name -> dataset column (names differ only in prefix and punctuation)
GENERATION_COLUMNS = {
    "biomass": "generation biomass",
    "fossil_brown_coal_lignite": "generation fossil brown coal/lignite",
    "fossil_gas": "generation fossil gas",
    "fossil_hard_coal": "generation fossil hard coal",
    "fossil_oil": "generation fossil oil",
    "hydro_pumped_storage_consumption": "generation hydro pumped storage consumption",
    "hydro_run_of_river_and_poundage": "generation hydro run-of-river and poundage",
    "hydro_water_reservoir": "generation hydro water reservoir",
    "nuclear": "generation nuclear",
    "other": "generation other",
    "other_renewable": "generation other renewable",
    "solar": "generation solar",
    "waste": "generation waste",
    "wind_onshore": "generation wind onshore",
}


def _clean(value):
    # NaN is not valid JSON and maps to NULL in both databases
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def row_to_reading(timestamp, row):
    """One cleaned-dataframe row (dataset column names) -> API-shaped dict."""
    reading = {"timestamp": timestamp.to_pydatetime()}
    for field, col in READING_FIELDS.items():
        reading[field] = _clean(row[col])
    reading["generation"] = {src: _clean(row[col]) for src, col in GENERATION_COLUMNS.items()}
    return reading


def readings_to_frame(readings):
    """API JSON readings -> dataframe shaped like load_and_clean's output:
    original dataset column names, UTC DatetimeIndex, sorted by time."""
    rows = []
    for r in readings:
        row = {col: r[field] for field, col in READING_FIELDS.items()}
        row.update({GENERATION_COLUMNS[name]: mw for name, mw in r["generation"].items()})
        row["time"] = r["timestamp"]
        rows.append(row)
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    # None (JSON null) -> NaN so pandas maths works as on the cleaned CSV
    return df.set_index("time").sort_index().astype(float)
