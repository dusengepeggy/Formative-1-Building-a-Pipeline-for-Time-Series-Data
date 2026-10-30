"""CRUD + time-series endpoints backed by MongoDB (prefix /mongo).

Same paths, parameters and JSON shape as the /sql router. /latest and /range
are declared BEFORE /{timestamp} so they are not parsed as timestamps.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from src.api.schemas import ReadingCreate, ReadingOut, ReadingUpdate, to_utc
from src.db.mongo import FIELD_PATHS, document_to_reading, get_readings_collection, reading_to_document

router = APIRouter(prefix="/mongo", tags=["MongoDB"])

MAX_LIMIT = 1000
NO_ID = {"_id": 0}  # ObjectId isn't part of the API shape


def _not_found(ts: datetime):
    return HTTPException(status.HTTP_404_NOT_FOUND, f"No reading at {to_utc(ts).isoformat()}")


@router.post("/readings", response_model=ReadingOut, status_code=status.HTTP_201_CREATED)
def create_reading(body: ReadingCreate, coll: Collection = Depends(get_readings_collection)):
    doc = reading_to_document(body.model_dump())
    try:
        coll.insert_one(doc)
    except DuplicateKeyError:  # unique index on timestamp
        raise HTTPException(status.HTTP_409_CONFLICT, f"Reading at {body.timestamp.isoformat()} exists")
    return document_to_reading(doc)


@router.get("/readings/latest", response_model=ReadingOut)
def latest_reading(coll: Collection = Depends(get_readings_collection)):
    doc = coll.find_one({}, NO_ID, sort=[("timestamp", -1)])
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No readings")
    return document_to_reading(doc)


@router.get("/readings/range", response_model=list[ReadingOut])
def readings_in_range(start: datetime, end: datetime,
                      limit: int = Query(500, ge=1, le=MAX_LIMIT),
                      offset: int = Query(0, ge=0),
                      coll: Collection = Depends(get_readings_collection)):
    """Readings with start <= timestamp <= end, oldest first."""
    start, end = to_utc(start), to_utc(end)
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "start must be <= end")
    cursor = (coll.find({"timestamp": {"$gte": start, "$lte": end}}, NO_ID)
              .sort("timestamp", 1).skip(offset).limit(limit))
    return [document_to_reading(d) for d in cursor]


@router.get("/readings", response_model=list[ReadingOut])
def list_readings(limit: int = Query(100, ge=1, le=MAX_LIMIT),
                  offset: int = Query(0, ge=0),
                  coll: Collection = Depends(get_readings_collection)):
    cursor = coll.find({}, NO_ID).sort("timestamp", 1).skip(offset).limit(limit)
    return [document_to_reading(d) for d in cursor]


@router.get("/readings/{timestamp}", response_model=ReadingOut)
def get_reading(timestamp: datetime, coll: Collection = Depends(get_readings_collection)):
    doc = coll.find_one({"timestamp": to_utc(timestamp)}, NO_ID)
    if doc is None:
        raise _not_found(timestamp)
    return document_to_reading(doc)


@router.put("/readings/{timestamp}", response_model=ReadingOut)
def update_reading(timestamp: datetime, body: ReadingUpdate,
                   coll: Collection = Depends(get_readings_collection)):
    changes = body.model_dump(exclude_unset=True)
    generation = changes.pop("generation", None) or {}
    # Dotted paths update only the given fields, leaving the rest of the document
    updates = {FIELD_PATHS[f]: v for f, v in changes.items()}
    updates.update({f"generation.{name}": mw for name, mw in generation.items()})
    query = {"timestamp": to_utc(timestamp)}
    if updates:
        doc = coll.find_one_and_update(query, {"$set": updates}, projection=NO_ID,
                                       return_document=ReturnDocument.AFTER)
    else:
        doc = coll.find_one(query, NO_ID)
    if doc is None:
        raise _not_found(timestamp)
    return document_to_reading(doc)


@router.delete("/readings/{timestamp}", response_model=ReadingOut)
def delete_reading(timestamp: datetime, coll: Collection = Depends(get_readings_collection)):
    """Deletes the hour; returns what was deleted."""
    doc = coll.find_one_and_delete({"timestamp": to_utc(timestamp)}, projection=NO_ID)
    if doc is None:
        raise _not_found(timestamp)
    return document_to_reading(doc)
