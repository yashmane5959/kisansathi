"""SQLAlchemy models for KisanSathi agricultural farm agent."""

from datetime import datetime
from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    salt = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    phone = Column(String(32), nullable=True)
    language = Column(String(32), default="Marathi", nullable=False)
    village = Column(String(128), nullable=True)
    district = Column(String(128), nullable=True)
    state = Column(String(128), nullable=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    soil_texture = Column(String(64), nullable=True)
    soil_ph = Column(Float, nullable=True)
    soil_oc = Column(Float, nullable=True)
    telegram_chat_id = Column(String(64), nullable=True)
    link_code = Column(String(32), nullable=True)
    demo_scenario = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    crops = relationship("Crop", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    snapshots = relationship("ForecastSnapshot", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    token = Column(String(128), primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="sessions")


class Crop(Base):
    __tablename__ = "crops"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    crop = Column(String(64), nullable=False)
    area_acres = Column(Float, default=1.0, nullable=False)
    sowing_date = Column(Date, nullable=False)
    irrigation_type = Column(String(32), default="drip", nullable=False)  # rainfed, drip, flood
    last_watered = Column(Date, nullable=True)
    status = Column(String(32), default="active", nullable=False)  # active, harvested
    roadmap_json = Column(Text, nullable=True)
    roadmap_lang = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="crops")
    watering_logs = relationship("WateringLog", back_populates="crop", cascade="all, delete-orphan")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(32), nullable=False)  # briefing, watering, climate, forecast_change, fertiliser, info
    severity = Column(String(32), default="info", nullable=False)  # info, warning, danger
    title = Column(String(256), nullable=False)
    body = Column(Text, nullable=False)
    dedupe_key = Column(String(128), index=True, nullable=True)
    read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")


class WateringLog(Base):
    __tablename__ = "watering_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    crop_id = Column(Integer, ForeignKey("crops.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    action = Column(String(32), nullable=False)  # watered, skipped
    mm_applied = Column(Float, default=0.0, nullable=False)
    mm_saved = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    crop = relationship("Crop", back_populates="watering_logs")


class ForecastSnapshot(Base):
    __tablename__ = "forecast_snapshots"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    taken_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    summary_json = Column(Text, nullable=False)  # 3-day totals: rain_mm, tmax, tmin

    user = relationship("User", back_populates="snapshots")
