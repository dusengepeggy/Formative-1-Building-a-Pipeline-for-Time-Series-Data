"""Load the cleaned dataset into MongoDB (one document per hour).

Usage (repo root):
    python -m database.mongo.load_data

Idempotent: each hour is upserted by its unique timestamp, so re-running
replaces documents instead of duplicating them. Also writes
database/mongo/sample_documents.json from the loaded data.
"""
import argparse
from pathlib import Path

from bson import json_util
from pymongo import ReplaceOne

from src.common.columns import row_to_reading
from src.db.mongo import ensure_indexes, get_client, get_collection, reading_to_document
from src.preprocessing.pipeline import load_and_clean

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data" / "raw" / "energy_dataset.csv"
SAMPLES_PATH = Path(__file__).resolve().parent / "sample_documents.json"
CHUNK = 5_000


def main():
    parser = argparse.ArgumentParser(description="Load the cleaned dataset into MongoDB")
    parser.add_argument("--data", default=DATA_PATH)
    args = parser.parse_args()

    df = load_and_clean(args.data)
    coll = get_collection(get_client())
    ensure_indexes(coll)

    ops = [ReplaceOne({"timestamp": doc["timestamp"]}, doc, upsert=True)
           for doc in (reading_to_document(row_to_reading(ts, row)) for ts, row in df.iterrows())]
    for i in range(0, len(ops), CHUNK):
        # unordered: the server can apply a batch in parallel
        coll.bulk_write(ops[i:i + CHUNK], ordered=False)

    print(f"{coll.name}: {coll.count_documents({}):,} documents")

    # Sample documents: first hour, highest-price hour, last hour
    samples = [coll.find_one({}, sort=[("timestamp", 1)], projection={"_id": 0}),
               coll.find_one({}, sort=[("price.actual", -1)], projection={"_id": 0}),
               coll.find_one({}, sort=[("timestamp", -1)], projection={"_id": 0})]
    SAMPLES_PATH.write_text(json_util.dumps(samples, indent=2,
                                            json_options=json_util.RELAXED_JSON_OPTIONS) + "\n")
    print(f"Wrote {len(samples)} sample documents to {SAMPLES_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
