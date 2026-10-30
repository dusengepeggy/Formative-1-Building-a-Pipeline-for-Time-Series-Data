-- Analytical queries on the MySQL schema. Times are UTC.
-- Each query starts with a "-- name:" line; scripts/run_db_queries.py runs
-- them and records the real output in reports/db_query_results.md.

-- name: avg_price_by_month
-- Average, min and max price per calendar month (all years together).
-- Shows the seasonal price pattern; compare with the MongoDB $group version.
SELECT MONTH(reading_time)          AS month,
       COUNT(*)                     AS hours,
       ROUND(AVG(price_actual), 2)  AS avg_price,
       ROUND(MIN(price_actual), 2)  AS min_price,
       ROUND(MAX(price_actual), 2)  AS max_price
FROM energy_readings
GROUP BY MONTH(reading_time)
ORDER BY month;

-- name: top_price_hours_renewables
-- The 10 most expensive hours and how much renewable generation they had.
-- Three-table join; the inner ORDER BY ... LIMIT uses idx_readings_price_actual.
SELECT e.reading_time,
       e.price_actual,
       e.total_load_actual,
       ROUND(SUM(g.generation_mw))                             AS renewable_mw,
       ROUND(100 * SUM(g.generation_mw) / e.total_load_actual, 1) AS renewable_share_pct
FROM (SELECT * FROM energy_readings
      ORDER BY price_actual DESC, reading_time
      LIMIT 10) AS e
JOIN generation_readings g ON g.reading_time = e.reading_time
JOIN generation_sources  s ON s.source_id = g.source_id AND s.category = 'renewable'
GROUP BY e.reading_time, e.price_actual, e.total_load_actual
ORDER BY e.price_actual DESC, e.reading_time;

-- name: daily_price_7day_moving_average
-- Daily average price in December 2018 with a 7-day moving average (window
-- function). The CTE starts 6 days early so the first December values have a
-- full window. Note: 2018-12-31 has 23 hours because the data ends 22:00 UTC.
WITH daily AS (
    SELECT DATE(reading_time) AS day, AVG(price_actual) AS avg_price
    FROM energy_readings
    WHERE reading_time >= '2018-11-25' AND reading_time < '2019-01-01'
    GROUP BY DATE(reading_time)
), smoothed AS (
    SELECT day,
           avg_price,
           AVG(avg_price) OVER (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS ma_7d
    FROM daily
)
SELECT day, ROUND(avg_price, 2) AS avg_price, ROUND(ma_7d, 2) AS ma_7d
FROM smoothed
WHERE day >= '2018-12-01'
ORDER BY day;

-- name: date_range_scan
-- All readings in a time window (the API's range endpoint pattern), with solar
-- and wind pivoted from the long generation table. Uses the reading_time PKs.
SELECT e.reading_time,
       e.price_actual,
       e.total_load_actual,
       MAX(CASE WHEN s.name = 'solar'        THEN g.generation_mw END) AS solar_mw,
       MAX(CASE WHEN s.name = 'wind_onshore' THEN g.generation_mw END) AS wind_onshore_mw
FROM energy_readings e
JOIN generation_readings g ON g.reading_time = e.reading_time
JOIN generation_sources  s ON s.source_id = g.source_id
WHERE e.reading_time BETWEEN '2018-12-31 06:00:00' AND '2018-12-31 11:00:00'
GROUP BY e.reading_time, e.price_actual, e.total_load_actual
ORDER BY e.reading_time;

-- name: generation_mix_by_year
-- Generation per category per UTC calendar year in GWh (hourly MW summed = MWh).
-- Pumped-storage consumption is excluded because it is load, not generation.
-- The single 2014-12-31 23:00 UTC hour is left out so years are complete.
SELECT YEAR(g.reading_time)             AS year,
       s.category,
       ROUND(SUM(g.generation_mw) / 1000) AS generation_gwh
FROM generation_readings g
JOIN generation_sources  s ON s.source_id = g.source_id
WHERE s.name <> 'hydro_pumped_storage_consumption'
  AND g.reading_time >= '2015-01-01'
GROUP BY YEAR(g.reading_time), s.category
ORDER BY year, generation_gwh DESC;
