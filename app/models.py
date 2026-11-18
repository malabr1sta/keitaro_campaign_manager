from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class CreationOperation(Base):
    __tablename__ = "creation_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(128), unique=True)
    alias: Mapped[str] = mapped_column(String(64), unique=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    stage: Mapped[str] = mapped_column(String(64), default="pending")
    campaign_id: Mapped[int | None] = mapped_column(Integer)
    geo_stream_id: Mapped[int | None] = mapped_column(Integer)
    offer_stream_id: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
