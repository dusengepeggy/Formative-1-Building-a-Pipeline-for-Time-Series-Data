"""Train the 24h-ahead price model and save it for the forecast script.

Usage (from the repo root):
    python -m src.models.train                      # chosen experiment
    python -m src.models.train --experiment hgb     # any key of EXPERIMENTS

The experiments are shared with notebooks/02_modeling.ipynb, which runs all of
them and picks the one with the lowest cross-validated MAE.
"""
import argparse
from pathlib import Path

import joblib
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.models.evaluate import evaluate
from src.preprocessing.pipeline import NEW_FEATS, TARGET, build_features, load_and_clean

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data" / "raw" / "energy_dataset.csv"
MODEL_PATH = ROOT / "models" / "price_model.joblib"

# Chronological split: no shuffling, the test year is never seen during tuning
TRAIN_END = "2017-12-31"
TEST_START = "2018-01-01"
CAL_COLS = ["hour", "dayofweek", "month"]

# Lowest cv_MAE in the notebook's results table (reports/experiment_table.csv)
CHOSEN_EXPERIMENT = "hgb"


def load_dataset(path=DATA_PATH):
    """Cleaned raw data plus the feature table (target joined, warm-up rows dropped)."""
    df = load_and_clean(path)
    data = build_features(df).join(df[TARGET]).dropna()
    return df, data


def split(data):
    train = data.loc[:TRAIN_END]
    test = data.loc[TEST_START:]
    return (train.drop(columns=TARGET), train[TARGET],
            test.drop(columns=TARGET), test[TARGET])


def feature_sets(X):
    """v1 = the original 18 features; v2 = v1 plus NEW_FEATS."""
    return {"v1": [c for c in X.columns if c not in NEW_FEATS],
            "v2": list(X.columns)}


def _cv():
    return TimeSeriesSplit(n_splits=5)


def ridge_search():
    model = Pipeline([("scale", StandardScaler()), ("model", Ridge())])
    return GridSearchCV(model, {"model__alpha": [0.1, 1, 10, 100]},
                        cv=_cv(), scoring="neg_mean_absolute_error")


def rf_search():
    grid = {"n_estimators": [100, 300],
            "max_depth": [8, 16, None],
            "min_samples_leaf": [1, 5, 20]}
    return GridSearchCV(RandomForestRegressor(random_state=42, n_jobs=-1), grid,
                        cv=_cv(), scoring="neg_mean_absolute_error")


def ridge_onehot_search():
    # One-hot calendar columns let a linear model learn a separate level per
    # hour/day/month instead of forcing a straight-line effect.
    pre = ColumnTransformer([("cal", OneHotEncoder(handle_unknown="ignore"), CAL_COLS)],
                            remainder=StandardScaler())
    model = Pipeline([("pre", pre), ("model", Ridge())])
    return GridSearchCV(model, {"model__alpha": [0.01, 0.1, 1, 10, 100]},
                        cv=_cv(), scoring="neg_mean_absolute_error")


def hgb_search():
    grid = {"learning_rate": [0.03, 0.1], "max_depth": [3, 6, None],
            "min_samples_leaf": [20, 50], "max_iter": [300, 600]}
    return GridSearchCV(HistGradientBoostingRegressor(random_state=42), grid,
                        cv=_cv(), scoring="neg_mean_absolute_error")


# key -> (table label, feature set, search factory)
EXPERIMENTS = {
    "ridge": ("Ridge (tuned)", "v1", ridge_search),
    "random_forest": ("Random Forest (tuned)", "v1", rf_search),
    "ridge_onehot": ("Ridge one-hot calendar (tuned)", "v2", ridge_onehot_search),
    "hgb": ("HistGradientBoosting (tuned)", "v2", hgb_search),
}


def run_experiment(key, X_train, y_train):
    """Fit one experiment's grid search; returns (search, feature list used)."""
    _, fset, make_search = EXPERIMENTS[key]
    features = feature_sets(X_train)[fset]
    search = make_search()
    search.fit(X_train[features], y_train)
    return search, features


def save_model(model, features, path=MODEL_PATH):
    # predict.py selects columns with `features`, so order must match training
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": list(features)}, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--experiment", choices=EXPERIMENTS, default=CHOSEN_EXPERIMENT)
    parser.add_argument("--data", default=DATA_PATH)
    parser.add_argument("--out", default=MODEL_PATH)
    args = parser.parse_args()

    _, data = load_dataset(args.data)
    X_train, y_train, X_test, y_test = split(data)
    search, features = run_experiment(args.experiment, X_train, y_train)
    save_model(search.best_estimator_, features, args.out)

    print(f"Experiment: {EXPERIMENTS[args.experiment][0]} ({len(features)} features)")
    print(f"Best params: {search.best_params_}")
    print(f"cv_MAE: {-search.best_score_:.3f}")
    print(f"Test: {evaluate(y_test, search.predict(X_test[features]))}")
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
