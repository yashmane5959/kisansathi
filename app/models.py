"""SQLAlchemy 2.0 data models for KisanSathi farm management."""

from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    language: Mapped[str] = mapped_column(String(32), default="Marathi", nullable=False)
    village: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    district: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    soil_texture: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    soil_ph: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    soil_oc: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    link_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    demo_scenario: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    crops: Mapped[list["Crop"]] = relationship("Crop", back_populates="user", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    forecast_snapshots: Mapped[list["ForecastSnapshot"]] = relationship("ForecastSnapshot", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped["User"] = relationship("User", back_populates="sessions")


class Crop(Base):
    __tablename__ = "crops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    crop: Mapped[str] = mapped_column(String(64), nullable=False)
    area_acres: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    sowing_date: Mapped[date] = mapped_column(Date, nullable=False)
    irrigation_type: Mapped[str] = mapped_column(String(32), default="drip", nullable=False)  # rainfed, drip, flood
    last_watered: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)  # active, harvested
    roadmap_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    roadmap_lang: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped["User"] = relationship("User", back_populates="crops")
    watering_logs: Mapped[list["WateringLog"]] = relationship("WateringLog", back_populates="crop", cascade="all, delete-orphan")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # briefing, watering, climate, forecast_change, fertiliser, info
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)  # info, warning, danger
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped["User"] = relationship("User", back_populates="notifications")


class WateringLog(Base):
    __tablename__ = "watering_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crop_id: Mapped[int] = mapped_column(Integer, ForeignKey("crops.id", ondelete="CASCADE"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # watered, skipped
    mm_applied: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    mm_saved: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    crop: Mapped["Crop"] = relationship("Crop", back_populates="watering_logs")


class ForecastSnapshot(Base):
    __tablename__ = "forecast_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="forecast_snapshots")
