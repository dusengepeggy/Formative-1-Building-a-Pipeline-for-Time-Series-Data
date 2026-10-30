# Building a Pipeline for Time-Series Data: Spain Electricity Prices

An end-to-end pipeline for hourly Spanish electricity data: exploratory analysis,
a 24-hour-ahead price forecasting model, storage in MySQL and MongoDB, a REST API
over both databases, and a script that forecasts from data fetched through that API.

## Problem definition

Forecast the **actual electricity price** (`price actual`, EUR/MWh) for hour **T**,
**24 hours in advance**. The features for hour T may only use:

- observed data from **T-24h or earlier** (price lags of 24/48/72/168 h, 24 h and 168 h
  moving averages of price, and the load and generation values lagged 24 h), and
- the grid operator's **day-ahead forecasts for T itself** (total load, solar and onshore
  wind). These are published the day before, so they are known at forecast time.

`tests/test_pipeline.py` checks this rule automatically.

## Dataset

- **Source:** Kaggle, *Hourly energy demand generation and weather* (Spain), file
  `energy_dataset.csv`:
  <https://www.kaggle.com/datasets/nicholasjhana/energy-consumption-generation-prices-and-weather>
- **Why this dataset:** it is a genuine hourly time series covering four full years, with a
  clear forecasting target (the actual price). It includes the operator's own forecasts and
  day-ahead price, which give realistic inputs and a benchmark to beat. It also has a
  generation mix that suits both a normalised relational schema and embedded documents.
- **Facts** (from `load_and_clean` in `src/preprocessing/pipeline.py`):
  - 35,064 hourly rows, 2015-01-01 00:00 to 2018-12-31 23:00 Madrid time. **Stored and
    served in UTC**, so the data runs from 2014-12-31T23:00:00Z to 2018-12-31T22:00:00Z.
  - Raw: 28 data columns. Dropped 2 all-empty columns (`generation hydro pumped storage
    aggregated`, `forecast wind offshore eday ahead`) and 6 all-zero columns (fossil
    coal-derived gas, oil shale, peat, geothermal, marine, wind offshore). That leaves 20.
  - 292 missing cells in 46 rows. Gaps of up to 6 hours are filled by time interpolation.
    Two values remain missing: `total load actual` at 2015-02-01 17:00 and 18:00 UTC (part
    of a longer gap). They are stored as `NULL`/`null` rather than invented.

## Results

The chronological split trains on data up to 2017-12-31 and tests on 2018. Hyperparameters
are tuned with `TimeSeriesSplit` (5 folds) and `GridSearchCV`, scored on MAE. **The model
is chosen by cross-validated MAE only, never by test score.** Full table:
[`reports/experiment_table.csv`](reports/experiment_table.csv).

| Experiment | Features | Test MAE | Test R2 | cv_MAE |
|---|---|---|---|---|
| Baseline: same hour yesterday | - | 5.205 | 0.603 | |
| Benchmark: market day-ahead price | - | 8.861 | 0.051 | |
| Ridge (tuned) | v1 (18) | 4.281 | 0.750 | 4.762 |
| Random Forest (tuned) | v1 (18) | 4.412 | 0.737 | 4.837 |
| Ridge, one-hot calendar (tuned) | v2 (20) | 4.241 | 0.754 | 4.805 |
| **HistGradientBoosting (tuned), chosen** | v2 (20) | 4.376 | 0.745 | **4.581** |

v2 adds `residual_load_forecast` and `is_holiday` (Spanish national holidays) to v1.

## Repository structure

```
data/raw/energy_dataset.csv     Kaggle data (never modified)
notebooks/
  01_eda_and_analysis.ipynb     Task 1: exploration and analysis
  02_modeling.ipynb             Task 1: experiments and model selection
src/
  preprocessing/pipeline.py     load_and_clean + build_features (single source of truth)
  models/evaluate.py            metrics (MAE, RMSE, R2)
  models/train.py               experiments + training CLI -> models/price_model.joblib
  common/columns.py             API field names <-> dataset column names
  db/sql.py                     SQLAlchemy engine, session, ORM models
  db/mongo.py                   MongoDB client, document <-> reading conversion
  api/main.py                   FastAPI app (+ /health)
  api/schemas.py                Pydantic request/response models
  api/routers/sql_routes.py     /sql endpoints
  api/routers/mongo_routes.py   /mongo endpoints
database/
  sql/schema.sql                MySQL schema (4 tables, indexes)
  sql/load_data.py              idempotent MySQL loader
  sql/queries.sql               analytical SQL queries
  mongo/design.md               collection design and rationale
  mongo/load_data.py            idempotent MongoDB loader
  mongo/queries.js              analytical MongoDB queries
  mongo/sample_documents.json   3 real documents
  erd/erd.puml                  ER diagram (PlantUML; erd.mmd = Mermaid version)
scripts/
  run_db_queries.py             runs all queries -> reports/db_query_results.md
  smoke_test_api.py             live test of every endpoint
  predict.py                    Task 4: forecast from API data
tests/                          pytest suite (API on both backends, leakage check)
reports/
  report.md / report.pdf        group report (all four tasks)
  experiment_table.csv          Task 1 results
  db_query_results.md           Task 2 query outputs
  figures/                      feature importance, predicted vs actual
models/                         trained model (generated, gitignored)
docker-compose.yml              optional local MySQL 8 + MongoDB 7
```

## Setup

Requires Python 3.14 (the versions in `requirements.txt` were tested with 3.14.7).
Commands run from the repo root.

**PowerShell (Windows)**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

**bash (macOS/Linux)**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` holds `MYSQL_URL`, `MONGO_URL`, `MONGO_DB` and `API_BASE_URL`. It is gitignored, so
never commit real credentials. The defaults match `docker-compose.yml`.

### Databases

**Option A, Docker (recommended):** start Docker Desktop, then run:
```bash
docker compose up -d
```
This starts MySQL 8 on port 3306 (database/user/password `energy`) and MongoDB 7 on port
27017, with data kept in named volumes.

**Option B, local installs:** install MySQL 8 and MongoDB, create a database and user, and
point `MYSQL_URL` / `MONGO_URL` in `.env` at them.

**Create the MySQL schema** (safe to re-run):
```powershell
# PowerShell with Docker
Get-Content database\sql\schema.sql -Raw | docker compose exec -T mysql mysql -uenergy -penergy energy
```
```bash
# bash with Docker
docker compose exec -T mysql mysql -uenergy -penergy energy < database/sql/schema.sql
# local MySQL client
mysql -u energy -p energy < database/sql/schema.sql
```

**Load the data.** Both loaders are idempotent, so re-running them updates rows instead of
duplicating them:
```bash
python -m database.sql.load_data
python -m database.mongo.load_data
```
Expected output:
```
generation_sources: 14 rows
energy_readings: 35,064 rows
generation_readings: 490,896 rows
energy_readings: 35,064 documents
Wrote 3 sample documents to database\mongo\sample_documents.json
```

**Run the analytical queries** and record their results in `reports/db_query_results.md`:
```bash
python scripts/run_db_queries.py
```

The ER diagram is `database/erd/erd.puml` (PlantUML; a Mermaid version is in `erd.mmd`).
It uses PlantUML's built-in `smetana` layout, so Graphviz is not needed. To render it to
`database/erd/erd.png`, either paste it into <https://www.plantuml.com/plantuml> or run:
```bash
java -jar plantuml.jar -tpng database/erd/erd.puml
```

## Notebooks and training

Open the notebooks in VS Code or Jupyter with the `.venv` kernel, or run them headlessly:
```bash
jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 notebooks/02_modeling.ipynb
```
`02_modeling.ipynb` runs every experiment, writes `reports/experiment_table.csv` and the
figures, and saves the chosen model. It took about 16 minutes on our machine, mostly the
Random Forest search.

To retrain only the chosen model (about 5 minutes):
```bash
python -m src.models.train                    # HistGradientBoosting (lowest cv_MAE)
python -m src.models.train --experiment ridge # any of: ridge, random_forest, ridge_onehot, hgb
```
It saves `models/price_model.joblib` as `{"model": ..., "features": [...]}`, where
`features` is the exact column order the model was trained on. The file is not committed,
so run this once after cloning.

## API

```bash
uvicorn src.api.main:app --reload
```
Interactive docs are at <http://127.0.0.1:8000/docs>.

The same endpoints exist under `/sql` (MySQL) and `/mongo` (MongoDB), and both return the
same JSON:

| Method | Path | Description | Codes |
|---|---|---|---|
| POST | `/{db}/readings` | Create a reading (all 14 generation sources required) | 201, 409 if the timestamp exists, 422 |
| GET | `/{db}/readings/latest` | Most recent reading | 200, 404 if empty |
| GET | `/{db}/readings/range?start=&end=&limit=&offset=` | Readings with start <= timestamp <= end, oldest first; `limit` default 500, max 1000 | 200, 422 |
| GET | `/{db}/readings?limit=&offset=` | Paginated list, oldest first; `limit` default 100, max 1000 | 200 |
| GET | `/{db}/readings/{timestamp}` | One reading | 200, 404 |
| PUT | `/{db}/readings/{timestamp}` | Full or partial update (only the fields sent change) | 200, 404, 422 |
| DELETE | `/{db}/readings/{timestamp}` | Delete; returns the deleted reading | 200, 404 |
| GET | `/health` | Status of each database | 200 |

**Timestamps are ISO 8601 in UTC**, e.g. `2018-12-31T22:00:00Z`. Readings must be on the
hour. Input with an offset is converted to UTC, and input without one is treated as UTC.

Reading shape:
```json
{
  "timestamp": "2018-12-31T22:00:00Z",
  "total_load_actual": 24455.0,
  "total_load_forecast": 24424.0,
  "price_actual": 69.88,
  "price_day_ahead": 64.27,
  "forecast_solar_day_ahead": 26.0,
  "forecast_wind_onshore_day_ahead": 3117.0,
  "generation": {"biomass": 290.0, "fossil_gas": 6926.0, "nuclear": 6075.0, "...": "14 sources"}
}
```

Examples:
```powershell
Invoke-RestMethod "http://127.0.0.1:8000/sql/readings/latest"
Invoke-RestMethod "http://127.0.0.1:8000/mongo/readings/range?start=2018-12-31T20:00:00Z&end=2018-12-31T22:00:00Z"
```
```bash
curl "http://127.0.0.1:8000/mongo/readings/2018-12-31T22:00:00Z"
curl -X PUT "http://127.0.0.1:8000/sql/readings/2018-12-31T22:00:00Z" \
     -H "Content-Type: application/json" -d '{"price_actual": 70.0}'
```

Live smoke test of every endpoint against the real databases (needs the API running; it
creates, updates and deletes a 2019-01-01 reading, so the data ends up unchanged):
```bash
python scripts/smoke_test_api.py
```

## Tests

```bash
pytest
```
The tests need no running database: `/sql` routes use SQLite in memory and `/mongo` routes
use mongomock. Each API test runs against both backends. There are 54 tests in total,
including the leakage check for `build_features`.

## Forecasting from the API (Task 4)

With the API running:
```bash
python scripts/predict.py --source sql   --target "2018-12-31T12:00:00Z"
python scripts/predict.py --source mongo --target "2018-12-31T12:00:00Z"
python scripts/predict.py --source mongo                 # target = latest record
python scripts/predict.py --source sql --target "2018-12-31T12:00:00Z" --save   # store in MySQL `predictions`
```
The script:

1. fetches readings from the target hour minus 216 hours up to the target hour from
   `/{source}/readings/range`;
2. converts them to the original dataset columns (`src/common/columns.py`);
3. runs `build_features` from the training pipeline;
4. loads `models/price_model.joblib` and selects the saved feature list in order;
5. predicts.

Output (identical for `sql` and `mongo`):
```
Source:       sql (http://127.0.0.1:8000)
Target hour:  2018-12-31T12:00:00Z (UTC)
History:      217 readings, 2018-12-22T12:00:00Z .. 2018-12-31T12:00:00Z
Model:        HistGradientBoostingRegressor:2d6cb3323bf6, 20 features
Forecast:     72.30 EUR/MWh
Actual:       71.80 EUR/MWh
Abs. error:   0.50 EUR/MWh
```
The `Model:` hash identifies the exact model file, so it will differ if you retrain.

**Notes**
- The dataset ends at 2018-12-31T22:00:00Z, so demonstrations use a target hour inside the
  dataset.
- The target hour itself must exist in the data, because its operator forecasts are
  features.
- At least 192 hours of history are required.
- The script stops with a clear message (exit code 1) if the API is unreachable, returns no
  data, or the history is too short. It does the same if a feature column is missing or
  contains NaN. For example, any target whose lags touch the two hours with no load value
  hits the NaN case.

## Team contributions

Based on the commit history:

| Member | Contributions |
|---|---|
|Muvunyi Innocent | Project scaffold, pinned requirements, `.env.example` and `.gitignore`, `docker-compose.yml`, Task 4 forecast script (`scripts/predict.py`) |
| Sheja Queen Linda | Raw dataset, EDA notebook, preprocessing pipeline updates, `evaluate.py` and `train.py`, modelling notebook and experiments |
| Sheja-Dorian | Column mapping, MySQL schema, SQLAlchemy models and loader, ER diagram, MongoDB design and loader, SQL and MongoDB queries with results |
| Peggy Dusenge | Repository setup, Task 3 API (schemas, MySQL and MongoDB routes, app), API and leakage tests, smoke test, README and report |
