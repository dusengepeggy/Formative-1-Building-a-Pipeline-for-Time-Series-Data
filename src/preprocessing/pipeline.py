import pandas as pd
import holidays

TARGET = "price actual"
HORIZON = 24                      # forecast 24 hours ahead
LAG_HOURS = [24, 48, 72, 168]
MA_WINDOWS = [24, 168]
LAGGED_COLS = ["total load actual", "generation fossil gas",
               "generation fossil hard coal", "generation wind onshore",
               "generation solar"]
FORECAST_COLS = ["total load forecast", "forecast solar day ahead",
                 "forecast wind onshore day ahead"]
# Added after the first round of experiments ("v2" feature set); the original
# "v1" set is every build_features column except these.
NEW_FEATS = ["residual_load_forecast", "is_holiday"]


def load_and_clean(path):
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    df = df.drop(columns=df.columns[df.isna().all()])
    df = df.loc[:, (df.fillna(0) != 0).any()]
    df = df.interpolate(method="time", limit=6)
    return df


def build_features(df):
    out = pd.DataFrame(index=df.index)
    price = df[TARGET]
    # Range extends past the dataset so new records posted via the API also get flagged
    es_holidays = holidays.Spain(years=range(2015, 2030))
    for lag in LAG_HOURS:
        out[f"price_lag_{lag}"] = price.shift(lag)

    for w in MA_WINDOWS:
        out[f"price_ma_{w}"] = price.shift(HORIZON).rolling(w).mean()

    for col in LAGGED_COLS:
        out[f"{col}_lag_{HORIZON}"] = df[col].shift(HORIZON)

    for col in FORECAST_COLS:
        out[col] = df[col]

    local = df.index.tz_convert("Europe/Madrid")
    out["hour"] = local.hour
    out["dayofweek"] = local.dayofweek
    out["is_weekend"] = (local.dayofweek >= 5).astype(int)
    out["month"] = local.month
    # Demand left for dispatchable (price-setting) plants after forecast wind and solar
    out["residual_load_forecast"] = (df["total load forecast"]
                                     - df["forecast wind onshore day ahead"]
                                     - df["forecast solar day ahead"])
    out["is_holiday"] = pd.Series(local.date, index=df.index).isin(es_holidays).astype(int)
    return out