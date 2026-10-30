-- MySQL 8 schema for the Spain hourly energy dataset.
-- Apply to an empty database (safe to re-run: every statement is IF NOT EXISTS).
--
-- Timestamps are DATETIME holding UTC. DATETIME is used instead of TIMESTAMP
-- because MySQL converts TIMESTAMP values with the session time zone; DATETIME
-- is stored exactly as given, so UTC in = UTC out.
--
-- Measurements are DOUBLE so the cleaned float64 values round-trip exactly:
-- the forecast script must build identical features from MySQL and MongoDB.

-- Lookup table: one row per generation type (seeded by load_data.py from
-- src/common/columns.py so names and categories live in one place).
CREATE TABLE IF NOT EXISTS generation_sources (
    source_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name      VARCHAR(64)       NOT NULL,
    -- NOTE: 'hydro_pumped_storage_consumption' is electricity CONSUMED for
    -- pumping, not generated. It is categorised 'other' and must be excluded
    -- when summing generation.
    category  ENUM('renewable', 'fossil', 'nuclear', 'other') NOT NULL,
    PRIMARY KEY (source_id),
    UNIQUE KEY uq_generation_sources_name (name)
);

-- One row per hour: load, prices and the operator's day-ahead forecasts.
CREATE TABLE IF NOT EXISTS energy_readings (
    reading_time                    DATETIME NOT NULL,  -- UTC, hour start
    -- Nullable: 2 hours (2015-02-01 17:00 and 18:00 UTC) sit in a gap longer
    -- than the cleaning step interpolates, so no value exists for them.
    total_load_actual               DOUBLE NULL,
    total_load_forecast             DOUBLE NOT NULL,
    price_actual                    DOUBLE NOT NULL,    -- EUR/MWh (no sign check: prices can be negative)
    price_day_ahead                 DOUBLE NOT NULL,
    forecast_solar_day_ahead        DOUBLE NOT NULL,
    forecast_wind_onshore_day_ahead DOUBLE NOT NULL,
    -- PK on reading_time already serves lookups by hour, date-range scans and
    -- "latest" (ORDER BY reading_time DESC LIMIT 1) without an extra index.
    PRIMARY KEY (reading_time),
    -- Supports "highest-price hours" queries (ORDER BY price_actual DESC LIMIT n)
    -- without sorting all 35k rows.
    KEY idx_readings_price_actual (price_actual),
    CONSTRAINT chk_readings_load_actual   CHECK (total_load_actual IS NULL OR total_load_actual >= 0),
    CONSTRAINT chk_readings_load_forecast CHECK (total_load_forecast >= 0),
    CONSTRAINT chk_readings_solar_fc      CHECK (forecast_solar_day_ahead >= 0),
    CONSTRAINT chk_readings_wind_fc       CHECK (forecast_wind_onshore_day_ahead >= 0)
);

-- Generation per source per hour (long format: 14 rows per hour).
CREATE TABLE IF NOT EXISTS generation_readings (
    reading_time  DATETIME          NOT NULL,
    source_id     SMALLINT UNSIGNED NOT NULL,
    generation_mw DOUBLE            NOT NULL,
    -- Composite PK leads with reading_time, so fetching the full mix for an
    -- hour or a time range (the API's access pattern) is an index range scan.
    PRIMARY KEY (reading_time, source_id),
    -- Per-source time series (e.g. solar over a month) would otherwise scan
    -- every source; this index also backs the source_id foreign key.
    KEY idx_generation_source_time (source_id, reading_time),
    -- Deleting an hour through the API removes its generation rows too.
    CONSTRAINT fk_generation_reading FOREIGN KEY (reading_time)
        REFERENCES energy_readings (reading_time) ON DELETE CASCADE,
    CONSTRAINT fk_generation_source FOREIGN KEY (source_id)
        REFERENCES generation_sources (source_id),
    CONSTRAINT chk_generation_non_negative CHECK (generation_mw >= 0)
);

-- Forecasts written by scripts/predict.py (Task 4). No foreign key to
-- energy_readings: a forecast can target an hour that is not recorded yet.
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id   INT UNSIGNED NOT NULL AUTO_INCREMENT,
    reading_time    DATETIME     NOT NULL,  -- UTC target hour
    predicted_price DOUBLE       NOT NULL,
    model_version   VARCHAR(64)  NOT NULL,
    created_at      DATETIME     NOT NULL DEFAULT (UTC_TIMESTAMP()),
    PRIMARY KEY (prediction_id),
    -- Look up all forecasts made for a given hour (e.g. to compare models).
    KEY idx_predictions_reading_time (reading_time)
);
