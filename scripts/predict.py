"""Forecast the electricity price 24 hours ahead from data served by the API (Task 4).

Usage (repo root, API running):
    python scripts/predict.py --source sql --target "2018-12-31T12:00:00Z"
    python scripts/predict.py --source mongo            # target = latest record
    python scripts/predict.py --source sql --save       # also store in MySQL `predictions`

Steps: fetch history from the API -> rebuild the dataset-shaped dataframe ->
build_features (same pipeline as training) -> load model -> predict.
The forecast for hour T uses only data up to T-24h plus the operator's
day-ahead forecasts for T, so it could have been made a day in advance.
"""
import argparse
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # allow `python scripts/...` from the repo root

import joblib  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from src.common.columns import readings_to_frame  # noqa: E402
from src.preprocessing.pipeline import TARGET, build_features  # noqa: E402

MODEL_PATH = ROOT / "models" / "price_model.joblib"
# 168h price lag, and the 168h moving average of prices shifted by 24h, reach
# back 191h; 216h (9 days) leaves a margin.
HISTORY_HOURS = 216
MIN_ROWS = 192  # hours T-191 .. T are the minimum build_features needs


class PredictError(Exception):
    """A problem the user can fix (API down, missing data, ...); printed without a traceback."""


def iso(ts):
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


# --- 1. fetch -----------------------------------------------------------------

def api_get(url, params=None):
    try:
        res = requests.get(url, params=params, timeout=30)
    except requests.ConnectionError:
        raise PredictError(f"API unreachable at {url}. Is it running? "
                           "Start it with: uvicorn src.api.main:app")
    except requests.Timeout:
        raise PredictError(f"API timed out: {url}")
    if res.status_code == 404:
        raise PredictError(f"Not found: {url} ({res.json().get('detail', '')})")
    if not res.ok:
        raise PredictError(f"API error {res.status_code} for {url}: {res.text[:200]}")
    return res.json()


def fetch_latest_timestamp(api_url, source):
    return pd.Timestamp(api_get(f"{api_url}/{source}/readings/latest")["timestamp"])


def fetch_history(api_url, source, target):
    start = target - pd.Timedelta(hours=HISTORY_HOURS)
    readings = api_get(f"{api_url}/{source}/readings/range",
                       params={"start": iso(start), "end": iso(target), "limit": 1000})
    if not readings:
        raise PredictError(f"API returned no readings between {iso(start)} and {iso(target)}")
    return readings


# --- 2. JSON -> dataframe ---------------------------------------------------

def to_frame(readings, target):
    df = readings_to_frame(readings)
    if target not in df.index:
        # The operator forecasts for T are features, so T itself must exist
        raise PredictError(f"No reading for the target hour {iso(target)}: its day-ahead "
                           "forecasts are required. Choose an hour that exists in the data.")
    # build_features shifts by rows, so missing hours must become NaN rows,
    # not silently shorten the lags
    df = df.asfreq("h")
    if len(df) < MIN_ROWS:
        raise PredictError(f"Only {len(df)} hours of history before {iso(target)}; "
                           f"need at least {MIN_ROWS}.")
    return df


# --- 3. features ------------------------------------------------------------

def target_features(df, target):
    # Same pipeline as training; never reimplemented here
    return build_features(df).loc[[target]]


# --- 4. model ---------------------------------------------------------------

def load_model(path):
    if not Path(path).exists():
        raise PredictError(f"Model file not found: {path}. Train it with: python -m src.models.train")
    bundle = joblib.load(path)
    return bundle["model"], bundle["features"], model_version(path, bundle["model"])


def model_version(path, model):
    # Content hash: identifies exactly which trained file made a prediction
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
    return f"{type(model).__name__}:{digest}"


def select_features(row, features):
    missing = [f for f in features if f not in row.columns]
    if missing:
        raise PredictError(f"Feature row is missing columns the model needs: {missing}")
    X = row[features]  # saved order = training order
    nan_cols = X.columns[X.isna().any()].tolist()
    if nan_cols:
        raise PredictError(f"NaN in features {nan_cols}: the history has gaps or nulls "
                           "the model can't use. Try another target hour.")
    return X


# --- 5. predict -------------------------------------------------------------

def save_prediction(target, price, version):
    from src.db.sql import Prediction, get_engine, make_session_factory
    with make_session_factory(get_engine())() as session:
        session.add(Prediction(reading_time=target.tz_convert("UTC").tz_localize(None).to_pydatetime(),
                               predicted_price=price, model_version=version))
        session.commit()


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="24h-ahead electricity price forecast from the API")
    parser.add_argument("--source", choices=["sql", "mongo"], default="sql")
    parser.add_argument("--target", help="UTC hour to forecast, e.g. 2018-12-31T12:00:00Z "
                                         "(default: latest record)")
    parser.add_argument("--api-url", default=os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument("--save", action="store_true", help="store the forecast in MySQL `predictions`")
    args = parser.parse_args()
    api_url = args.api_url.rstrip("/")

    try:
        if args.target:
            target = pd.Timestamp(args.target)
            target = target.tz_localize("UTC") if target.tzinfo is None else target.tz_convert("UTC")
        else:
            target = fetch_latest_timestamp(api_url, args.source)
        model, features, version = load_model(args.model)
        readings = fetch_history(api_url, args.source, target)
        df = to_frame(readings, target)
        X = select_features(target_features(df, target), features)
        forecast = float(model.predict(X)[0])
        if args.save:
            save_prediction(target, forecast, version)
    except PredictError as exc:
        sys.exit(f"Error: {exc}")

    actual = df.loc[target, TARGET]
    print(f"Source:       {args.source} ({api_url})")
    print(f"Target hour:  {iso(target)} (UTC)")
    print(f"History:      {len(readings)} readings, {iso(df.index[0])} .. {iso(df.index[-1])}")
    print(f"Model:        {version}, {len(features)} features")
    print(f"Forecast:     {forecast:.2f} EUR/MWh")
    if pd.notna(actual):
        print(f"Actual:       {actual:.2f} EUR/MWh")
        print(f"Abs. error:   {abs(forecast - actual):.2f} EUR/MWh")
    if args.save:
        print("Saved to MySQL table `predictions`.")


if __name__ == "__main__":
    main()
