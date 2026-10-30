# MongoDB collection design

Database `energy` (from `MONGO_DB`), one collection: **`energy_readings`**, one document per hour.

## Document shape

The last hour in the dataset, as stored:

```js
{
  timestamp: ISODate("2018-12-31T22:00:00Z"),          // UTC hour start, unique
  load:      { actual: 24455.0, forecast: 24424.0 },   // MW; actual may be null
  price:     { actual: 69.88, day_ahead: 64.27 },      // EUR/MWh
  forecasts: { solar_day_ahead: 26.0, wind_onshore_day_ahead: 3117.0 },  // MW
  generation: {                                        // MW per source, 14 keys
    biomass: 290.0, fossil_brown_coal_lignite: 0.0, fossil_gas: 6926.0,
    fossil_hard_coal: 2166.0, fossil_oil: 163.0,
    hydro_pumped_storage_consumption: 108.0,           // consumption, NOT generation
    hydro_run_of_river_and_poundage: 1069.0, hydro_water_reservoir: 1686.0,
    nuclear: 6075.0, other: 61.0, other_renewable: 92.0, solar: 31.0,
    waste: 287.0, wind_onshore: 3651.0
  },
  date_parts: { year: 2018, month: 12, dayofweek: 0, hour: 22 }  // UTC, 0 = Monday
}
```

Three real documents (first hour, highest-price hour, last hour) are in
[`sample_documents.json`](sample_documents.json), exported from the loaded collection
by `database/mongo/load_data.py`.

Field names match the API (`src/common/columns.py`): the generation keys are the same
source names as `generation_sources.name` in MySQL.

## Why embed the generation mix instead of referencing it

- **Read together.** Every consumer (the API, the forecast script, the analytical
  queries) needs an hour's prices, load and generation at the same time. Embedding
  returns all of it in one document read; MySQL needs a three-table join for the same
  answer (compare `top_price_hours_renewables` in both query files).
- **Bounded size.** There is a fixed set of 14 sources, so a document can't grow without
  limit (one of the main risks of embedding). Loaded documents are 619 to 627 bytes of BSON.
- **Written together.** An hour's generation is never updated independently of the hour
  itself, so there are no partial-update or consistency issues across documents.
- **No independent life.** A generation value has no meaning outside its hour, so it
  doesn't need its own collection. The source categories (renewable, fossil and so on)
  are reference data. They change rarely and are applied in queries, as in the
  renewable sum, rather than stored per document.

## Why a regular collection, not a native time-series collection

MongoDB time-series collections restrict updates and deletes, and the API must support
full CRUD (PUT and DELETE by timestamp). A regular collection with a unique `timestamp`
index gives the same one-document-per-hour guarantee without those restrictions. At 35,064
documents, the storage savings of a time-series collection don't matter.

## Indexes

| Index | Keys | Why |
|---|---|---|
| `uq_timestamp` | `{timestamp: 1}`, **unique** | One document per hour (POST returns 409 on duplicates, and upserts in the loader are idempotent). Also serves lookup by timestamp, date-range scans and "latest" (sort `timestamp` desc, limit 1). |
| `idx_price_actual` | `{"price.actual": -1}` | The highest-price-hours query sorts on price; the index avoids an in-memory sort of the whole collection. |
| `_id_` | `{_id: 1}` | Default. |

`date_parts` is not indexed: the month/year aggregations read every document anyway,
so an index would not help them. It is precomputed so `$group` needs no date operators.

## Nulls

`load.actual` is `null` for 2015-02-01 17:00 and 18:00 UTC. Those two hours fall in a gap
longer than the cleaning step interpolates (6 h), and we don't invent values. `$avg`
ignores nulls, the same as SQL `AVG`.
