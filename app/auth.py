"""Authentication, standard-library PBKDF2 hashing, and session management."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Session as DbSession, User

SESSION_LIFETIME_DAYS = 30


def hash_password(password: str) -> tuple[str, str]:
    """Hash a password using standard library PBKDF2-HMAC-SHA256 with 200,000 iterations.

    Returns:
        (hex_hash, hex_salt)
    """
    salt_bytes = secrets.token_bytes(16)
    hash_bytes = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        200_000,
    )
    return hash_bytes.hex(), salt_bytes.hex()


def verify_password(password: str, expected_hash_hex: str, salt_hex: str) -> bool:
    """Verify password hash using constant-time comparison."""
    salt_bytes = bytes.fromhex(salt_hex)
    computed_bytes = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        200_000,
    )
    expected_bytes = bytes.fromhex(expected_hash_hex)
    return hmac.compare_digest(computed_bytes, expected_bytes)


def create_user_session(db: Session, user_id: int) -> str:
    """Create a new 32-byte urlsafe session token and save it to the sessions table."""
    token = secrets.token_urlsafe(32)
    session_obj = DbSession(
        token=token,
        user_id=user_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(session_obj)
    db.commit()
    return token


def delete_user_session(db: Session, token: str) -> None:
    """Remove a session token from the database."""
    session_obj = db.query(DbSession).filter(DbSession.token == token).first()
    if session_obj:
        db.delete(session_obj)
        db.commit()


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency to authenticate the Bearer token and return the current User."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = authorization.split("Bearer ", 1)[1].strip()
    session_obj = db.query(DbSession).filter(DbSession.token == token).first()
    if not session_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    # Check expiration (30 days)
    now = datetime.now(timezone.utc)
    created_at = session_obj.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    if now - created_at > timedelta(days=SESSION_LIFETIME_DAYS):
        db.delete(session_obj)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please log in again",
        )

    user = db.query(User).filter(User.id == session_obj.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user
