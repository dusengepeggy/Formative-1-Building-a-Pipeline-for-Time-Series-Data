"""CRUD + time-series endpoints backed by MySQL (prefix /sql).

Routes are declared with /latest and /range BEFORE /{timestamp} so FastAPI
doesn't try to parse "latest" or "range" as a timestamp.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.schemas import ReadingCreate, ReadingOut, ReadingUpdate, to_utc
from src.common.columns import READING_FIELDS
from src.db.sql import EnergyReading, GenerationReading, GenerationSource, get_session

router = APIRouter(prefix="/sql", tags=["MySQL"])

MAX_LIMIT = 1000


def _db_time(ts: datetime) -> datetime:
    # DATETIME columns hold naive UTC
    return to_utc(ts).replace(tzinfo=None)


def _to_out(r: EnergyReading) -> dict:
    return {"timestamp": r.reading_time,
            **{f: getattr(r, f) for f in READING_FIELDS},
            "generation": dict(sorted((g.source.name, g.generation_mw) for g in r.generation))}


def _source_ids(session: Session) -> dict[str, int]:
    return dict(session.execute(select(GenerationSource.name, GenerationSource.source_id)).all())


def _get_or_404(session: Session, ts: datetime) -> EnergyReading:
    reading = session.get(EnergyReading, _db_time(ts))
    if reading is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No reading at {to_utc(ts).isoformat()}")
    return reading


@router.post("/readings", response_model=ReadingOut, status_code=status.HTTP_201_CREATED)
def create_reading(body: ReadingCreate, session: Session = Depends(get_session)):
    ts = _db_time(body.timestamp)
    if session.get(EnergyReading, ts) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Reading at {body.timestamp.isoformat()} exists")
    ids = _source_ids(session)
    reading = EnergyReading(
        reading_time=ts,
        **{f: getattr(body, f) for f in READING_FIELDS},
        generation=[GenerationReading(source_id=ids[name], generation_mw=mw)
                    for name, mw in body.generation.items()])
    session.add(reading)
    try:
        session.commit()
    except IntegrityError:  # another request inserted the same hour meanwhile
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"Reading at {body.timestamp.isoformat()} exists")
    return _to_out(reading)


@router.get("/readings/latest", response_model=ReadingOut)
def latest_reading(session: Session = Depends(get_session)):
    reading = session.scalars(
        select(EnergyReading).order_by(EnergyReading.reading_time.desc()).limit(1)).first()
    if reading is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No readings")
    return _to_out(reading)


@router.get("/readings/range", response_model=list[ReadingOut])
def readings_in_range(start: datetime, end: datetime,
                      limit: int = Query(500, ge=1, le=MAX_LIMIT),
                      offset: int = Query(0, ge=0),
                      session: Session = Depends(get_session)):
    """Readings with start <= timestamp <= end, oldest first."""
    if to_utc(start) > to_utc(end):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "start must be <= end")
    stmt = (select(EnergyReading)
            .where(EnergyReading.reading_time.between(_db_time(start), _db_time(end)))
            .order_by(EnergyReading.reading_time).offset(offset).limit(limit))
    return [_to_out(r) for r in session.scalars(stmt)]


@router.get("/readings", response_model=list[ReadingOut])
def list_readings(limit: int = Query(100, ge=1, le=MAX_LIMIT),
                  offset: int = Query(0, ge=0),
                  session: Session = Depends(get_session)):
    stmt = select(EnergyReading).order_by(EnergyReading.reading_time).offset(offset).limit(limit)
    return [_to_out(r) for r in session.scalars(stmt)]


@router.get("/readings/{timestamp}", response_model=ReadingOut)
def get_reading(timestamp: datetime, session: Session = Depends(get_session)):
    return _to_out(_get_or_404(session, timestamp))


@router.put("/readings/{timestamp}", response_model=ReadingOut)
def update_reading(timestamp: datetime, body: ReadingUpdate,
                   session: Session = Depends(get_session)):
    reading = _get_or_404(session, timestamp)
    changes = body.model_dump(exclude_unset=True)
    generation = changes.pop("generation", None) or {}
    for field, value in changes.items():
        setattr(reading, field, value)
    existing = {g.source.name: g for g in reading.generation}
    ids = _source_ids(session) if set(generation) - set(existing) else {}
    for name, mw in generation.items():
        if name in existing:
            existing[name].generation_mw = mw
        else:
            reading.generation.append(GenerationReading(source_id=ids[name], generation_mw=mw))
    session.commit()
    return _to_out(reading)


@router.delete("/readings/{timestamp}", response_model=ReadingOut)
def delete_reading(timestamp: datetime, session: Session = Depends(get_session)):
    """Deletes the hour (and its generation rows); returns what was deleted."""
    reading = _get_or_404(session, timestamp)
    out = _to_out(reading)
    session.delete(reading)
    session.commit()
    return out
