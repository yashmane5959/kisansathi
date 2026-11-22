"""Database connection, engine, and session management using SQLAlchemy 2.0."""

import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.config import settings

# Read DATABASE_URL from environment or settings
DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./kisansathi.db"

# Rewrite postgresql URL if needed for psycopg2
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db():
    """Ensure all models are registered and create tables."""
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)


# Auto-create tables on import so CLI scripts and test clients work immediately
init_db()


def get_db() -> Generator[Session, None, None]:
    """Dependency for yielding database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
