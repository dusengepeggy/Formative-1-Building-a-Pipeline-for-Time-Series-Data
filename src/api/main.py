"""FastAPI app exposing the energy readings from MySQL (/sql) and MongoDB (/mongo).

Run (repo root):  uvicorn src.api.main:app --reload
Interactive docs: http://127.0.0.1:8000/docs
"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from pymongo.collection import Collection
from pymongo.errors import PyMongoError
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.routers import mongo_routes, sql_routes
from src.db.mongo import ensure_indexes, get_readings_collection
from src.db.sql import get_session

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    # The unique timestamp index is what makes POST /mongo return 409, so make
    # sure it exists even on a fresh database. Don't block startup if Mongo is
    # down; /health will report it.
    try:
        ensure_indexes(get_readings_collection())
    except PyMongoError as exc:
        log.warning("Could not ensure MongoDB indexes: %s", exc)
    yield


app = FastAPI(
    title="Spain Energy Time-Series API",
    description="Hourly Spanish electricity readings (load, prices, generation mix). "
                "All timestamps are ISO 8601 in UTC.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(sql_routes.router)
app.include_router(mongo_routes.router)


@app.get("/health", tags=["Health"])
def health(session: Session = Depends(get_session),
           coll: Collection = Depends(get_readings_collection)):
    """Reports whether each database answers, so a failing one is easy to spot."""
    checks = {}
    try:
        session.execute(text("SELECT 1"))
        checks["mysql"] = "ok"
    except Exception as exc:  # report, don't crash: health must always answer
        checks["mysql"] = f"error: {type(exc).__name__}"
    try:
        coll.find_one({}, {"_id": 1})
        checks["mongo"] = "ok"
    except Exception as exc:
        checks["mongo"] = f"error: {type(exc).__name__}"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, **checks}
