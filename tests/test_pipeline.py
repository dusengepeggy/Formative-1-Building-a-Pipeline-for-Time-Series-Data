"""Leakage check: features for hour T may only use data from T-24h or earlier,
except the operator's day-ahead forecasts for T itself (known in advance)."""
import numpy as np
import pandas as pd

from src.preprocessing.pipeline import FORECAST_COLS, HORIZON, LAGGED_COLS, TARGET, build_features


def synthetic_frame(n=400, seed=0):
    rng = np.random.default_rng(seed)
    index = pd.date_range("2018-01-01", periods=n, freq="h", tz="UTC")
    cols = [TARGET, *LAGGED_COLS, *FORECAST_COLS]
    return pd.DataFrame(rng.uniform(100, 1000, (n, len(cols))), index=index, columns=cols)


def test_features_ignore_data_newer_than_horizon():
    df = synthetic_frame()
    t = df.index[300]
    cutoff = t - pd.Timedelta(hours=HORIZON)

    tampered = df.copy()
    recent = tampered.index > cutoff
    # Overwrite everything after T-24h, except the forecast columns at T itself
    non_forecast = [c for c in df.columns if c not in FORECAST_COLS]
    tampered.loc[recent, non_forecast] = -1.0
    tampered.loc[recent & (tampered.index != t), FORECAST_COLS] = -1.0

    original = build_features(df).loc[t]
    after = build_features(tampered).loc[t]
    pd.testing.assert_series_equal(original, after)


def test_check_is_sensitive_to_data_at_horizon():
    # Guard against a vacuous pass: changing T-24h itself must change features at T
    df = synthetic_frame()
    t = df.index[300]
    tampered = df.copy()
    tampered.loc[t - pd.Timedelta(hours=HORIZON), TARGET] = -1.0
    assert not build_features(df).loc[t].equals(build_features(tampered).loc[t])
