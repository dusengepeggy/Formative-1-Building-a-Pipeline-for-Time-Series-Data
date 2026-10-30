"""SQLAlchemy engine/session and ORM models mirroring database/sql/schema.sql.

All DATETIME columns hold naive UTC datetimes (see schema.sql for why).
"""
import os
from datetime import datetime, timezone
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import (CheckConstraint, DateTime, Double, Enum, ForeignKey, Index,
                        Integer, SmallInteger, String, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

load_dotenv()


class Base(DeclarativeBase):
    pass


class GenerationSource(Base):
    __tablename__ = "generation_sources"

    # SQLite (used in tests) only auto-increments INTEGER primary keys
    source_id: Mapped[int] = mapped_column(SmallInteger().with_variant(Integer, "sqlite"),
                                           primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    category: Mapped[str] = mapped_column(Enum("renewable", "fossil", "nuclear", "other",
                                               name="source_category"))


class EnergyReading(Base):
    __tablename__ = "energy_readings"
    __table_args__ = (Index("idx_readings_price_actual", "price_actual"),)

    reading_time: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    total_load_actual: Mapped[float | None] = mapped_column(Double)
    total_load_forecast: Mapped[float] = mapped_column(Double)
    price_actual: Mapped[float] = mapped_column(Double)
    price_day_ahead: Mapped[float] = mapped_column(Double)
    forecast_solar_day_ahead: Mapped[float] = mapped_column(Double)
    forecast_wind_onshore_day_ahead: Mapped[float] = mapped_column(Double)

    # selectin loads the generation mix for many readings in one extra query
    generation: Mapped[list["GenerationReading"]] = relationship(
        back_populates="reading", cascade="all, delete-orphan",
        passive_deletes=True, lazy="selectin")


class GenerationReading(Base):
    __tablename__ = "generation_readings"
    __table_args__ = (Index("idx_generation_source_time", "source_id", "reading_time"),
                      CheckConstraint("generation_mw >= 0", name="chk_generation_non_negative"))

    reading_time: Mapped[datetime] = mapped_column(
        DateTime, ForeignKey("energy_readings.reading_time", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("generation_sources.source_id"), primary_key=True)
    generation_mw: Mapped[float] = mapped_column(Double)

    reading: Mapped[EnergyReading] = relationship(back_populates="generation")
    source: Mapped[GenerationSource] = relationship(lazy="joined")


class Prediction(Base):
    __tablename__ = "predictions"

    prediction_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reading_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    predicted_price: Mapped[float] = mapped_column(Double)
    model_version: Mapped[str] = mapped_column(String(64))
    # Set in Python so it is UTC regardless of the database server's time zone
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


def get_engine(url=None):
    # pool_pre_ping avoids errors from connections MySQL closed while idle
    return create_engine(url or os.environ["MYSQL_URL"], pool_pre_ping=True)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@lru_cache
def _default_session_factory():
    # Created on first request, not at import, so tests can run without MySQL
    return make_session_factory(get_engine())


def get_session():
    """FastAPI dependency: one session per request, always closed."""
    with _default_session_factory()() as session:
        yield session
