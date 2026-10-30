// Analytical queries on the energy_readings collection. Times are UTC.
// Run in mongosh:  docker compose exec -T mongo mongosh energy --quiet < database/mongo/queries.js
// Each query starts with a "// name:" line; scripts/run_db_queries.py runs the
// same pipelines with pymongo and records the real output in
// reports/db_query_results.md. Keys are quoted so each pipeline is valid JSON.

// name: avg_price_by_month
// Average, min and max price per calendar month ($group on the precomputed
// date_parts). Should match the SQL avg_price_by_month query exactly.
printjson(db.energy_readings.aggregate([
  {"$group": {"_id": "$date_parts.month",
              "hours": {"$sum": 1},
              "avg_price": {"$avg": "$price.actual"},
              "min_price": {"$min": "$price.actual"},
              "max_price": {"$max": "$price.actual"}}},
  {"$sort": {"_id": 1}},
  {"$project": {"_id": 0, "month": "$_id", "hours": "$hours",
                "avg_price": {"$round": ["$avg_price", 2]},
                "min_price": {"$round": ["$min_price", 2]},
                "max_price": {"$round": ["$max_price", 2]}}}
]).toArray());

// name: date_range_scan
// All readings in a time window (the API's range endpoint pattern). Served by
// the unique timestamp index; generation is read from the same document.
printjson(db.energy_readings.aggregate([
  {"$match": {"timestamp": {"$gte": ISODate("2018-12-31T06:00:00Z"),
                            "$lte": ISODate("2018-12-31T11:00:00Z")}}},
  {"$sort": {"timestamp": 1}},
  {"$project": {"_id": 0, "timestamp": 1,
                "price_actual": "$price.actual",
                "total_load_actual": "$load.actual",
                "solar_mw": "$generation.solar",
                "wind_onshore_mw": "$generation.wind_onshore"}}
]).toArray());

// name: top_price_hours_renewables
// The 10 most expensive hours and their renewable generation. No join needed:
// the generation mix is embedded. Uses idx_price_actual for the sort.
printjson(db.energy_readings.aggregate([
  {"$sort": {"price.actual": -1, "timestamp": 1}},
  {"$limit": 10},
  {"$addFields": {"renewable_mw": {"$add": [
      "$generation.biomass", "$generation.hydro_run_of_river_and_poundage",
      "$generation.hydro_water_reservoir", "$generation.other_renewable",
      "$generation.solar", "$generation.wind_onshore"]}}},
  {"$project": {"_id": 0, "timestamp": 1,
                "price_actual": "$price.actual",
                "total_load_actual": "$load.actual",
                "renewable_mw": {"$round": ["$renewable_mw", 0]},
                "renewable_share_pct": {"$round": [
                    {"$multiply": [100, {"$divide": ["$renewable_mw", "$load.actual"]}]}, 1]}}}
]).toArray());

// name: yearly_averages
// Yearly averages of price, load, wind and solar (UTC years; the single
// 2014-12-31 23:00 UTC hour is excluded so every year is complete).
printjson(db.energy_readings.aggregate([
  {"$match": {"timestamp": {"$gte": ISODate("2015-01-01T00:00:00Z")}}},
  {"$group": {"_id": "$date_parts.year",
              "avg_price": {"$avg": "$price.actual"},
              "avg_load_mw": {"$avg": "$load.actual"},
              "avg_wind_mw": {"$avg": "$generation.wind_onshore"},
              "avg_solar_mw": {"$avg": "$generation.solar"}}},
  {"$sort": {"_id": 1}},
  {"$project": {"_id": 0, "year": "$_id",
                "avg_price": {"$round": ["$avg_price", 2]},
                "avg_load_mw": {"$round": ["$avg_load_mw", 0]},
                "avg_wind_mw": {"$round": ["$avg_wind_mw", 0]},
                "avg_solar_mw": {"$round": ["$avg_solar_mw", 0]}}}
]).toArray());
