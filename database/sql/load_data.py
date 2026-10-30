"""Load the cleaned dataset into MySQL.

Usage (repo root, after applying database/sql/schema.sql):
    python -m database.sql.load_data

Idempotent: rows are upserted (INSERT ... ON DUPLICATE KEY UPDATE), so
re-running updates values in place instead of duplicating them.
"""
import argparse
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert

from src.common.columns import GENERATION_COLUMNS, GENERATION_SOURCES, READING_FIELDS
from src.db.sql import EnergyReading, GenerationReading, GenerationSource, get_engine
from src.preprocessing.pipeline import load_and_clean

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "raw" / "energy_dataset.csv"
CHUNK = 10_000


def upsert(conn, model, rows, update_cols):
    stmt = insert(model)
    stmt = stmt.on_duplicate_key_update({c: stmt.inserted[c] for c in update_cols})
    # Chunks keep each executemany batch (and its memory) bounded
    for i in range(0, len(rows), CHUNK):
        conn.execute(stmt, rows[i:i + CHUNK])


def reading_rows(df, times):
    readings = df[list(READING_FIELDS.values())].set_axis(list(READING_FIELDS), axis=1)
    readings.insert(0, "reading_time", times)
    # NaN -> None so MySQL stores NULL
    return readings.astype(object).where(readings.notna(), None).to_dict("records")


def generation_rows(df, times, source_ids):
    gen = df[list(GENERATION_COLUMNS.values())].set_axis(list(GENERATION_COLUMNS), axis=1)
    gen.index = times
    gen.index.name = "reading_time"
    long = gen.reset_index().melt(id_vars="reading_time", var_name="source",
                                  value_name="generation_mw")
    long["source_id"] = long["source"].map(source_ids)
    return long[["reading_time", "source_id", "generation_mw"]].to_dict("records")


def main():
    parser = argparse.ArgumentParser(description="Load the cleaned dataset into MySQL")
    parser.add_argument("--data", default=DATA_PATH)
    args = parser.parse_args()

    df = load_and_clean(args.data)
    # Naive UTC datetimes for DATETIME columns
    times = list(df.index.tz_convert("UTC").tz_localize(None).to_pydatetime())

    engine = get_engine()
    with engine.begin() as conn:
        upsert(conn, GenerationSource,
               [{"name": n, "category": c} for n, c in GENERATION_SOURCES.items()],
               ["category"])
        source_ids = dict(conn.execute(select(GenerationSource.name, GenerationSource.source_id)).all())
        upsert(conn, EnergyReading, reading_rows(df, times), list(READING_FIELDS))
        upsert(conn, GenerationReading, generation_rows(df, times, source_ids), ["generation_mw"])

    with engine.connect() as conn:
        for model in (GenerationSource, EnergyReading, GenerationReading):
            count = conn.execute(select(func.count()).select_from(model)).scalar_one()
            print(f"{model.__tablename__}: {count:,} rows")


if __name__ == "__main__":
    main()
