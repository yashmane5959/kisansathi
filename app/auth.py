"""Authentication and authorization utilities for KisanSathi."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Session as SessionModel, User

security = HTTPBearer(auto_error=False)


def hash_password(password: str, salt_hex: Optional[str] = None) -> Tuple[str, str]:
    """Hash password using PBKDF2-HMAC-SHA256 with 200,000 iterations.
    
    Returns (salt_hex, hash_hex).
    """
    if salt_hex is None:
        salt_bytes = secrets.token_bytes(16)
        salt_hex = salt_bytes.hex()
    else:
        salt_bytes = bytes.fromhex(salt_hex)

    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, 200_000)
    return salt_hex, pw_hash.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    """Verify password against stored salt and hash."""
    try:
        salt_bytes = bytes.fromhex(salt_hex)
        pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, 200_000)
        return hmac.compare_digest(pw_hash.hex(), hash_hex)
    except Exception:
        return False


def create_session(db: Session, user_id: int) -> str:
    """Create a new 30-day session token for a user."""
    token = secrets.token_urlsafe(32)
    session_obj = SessionModel(
        token=token,
        user_id=user_id,
        created_at=datetime.utcnow(),
    )
    db.add(session_obj)
    db.commit()
    return token


def delete_session(db: Session, token: str) -> bool:
    """Delete a session token upon logout."""
    session_obj = db.query(SessionModel).filter(SessionModel.token == token).first()
    if session_obj:
        db.delete(session_obj)
        db.commit()
        return True
    return False


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db),
) -> User:
    """Dependency that resolves the active user from the Bearer token or raises 401."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is missing. Please provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    session_obj = db.query(SessionModel).filter(SessionModel.token == token).first()
    if not session_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 30-day session expiration
    if datetime.utcnow() - session_obj.created_at > timedelta(days=30):
        db.delete(session_obj)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == session_obj.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account associated with this token no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
