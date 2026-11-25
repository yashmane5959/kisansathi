"""API routes for authentication, farm profiles, and user management."""

import secrets
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import (
    create_session,
    delete_session,
    get_current_user,
    hash_password,
    security,
    verify_password,
)
from app.config import settings
from app.db import get_db
from app.models import User
from app.tools import geocode_place, get_soil_info

router = APIRouter(prefix="/api", tags=["Farm Auth & Profile"])


def serialize_user(user: User) -> Dict[str, Any]:
    """Helper to convert a User model instance into a JSON-friendly dict."""
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "phone": user.phone,
        "language": user.language,
        "village": user.village,
        "district": user.district,
        "state": user.state,
        "lat": user.lat,
        "lon": user.lon,
        "soil_texture": user.soil_texture,
        "soil_ph": user.soil_ph,
        "soil_oc": user.soil_oc,
        "telegram_chat_id": user.telegram_chat_id,
        "link_code": user.link_code,
        "demo_scenario": user.demo_scenario,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


# ===================== Schemas =====================

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, description="Unique username")
    password: str = Field(..., min_length=6, description="Password (min 6 characters)")
    name: str = Field(..., min_length=1, description="Farmer full name")
    language: Optional[str] = Field("Marathi", description="Preferred language")
    village: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    phone: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    language: Optional[str] = None
    village: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    phone: Optional[str] = None


# ===================== Auth Endpoints =====================

@router.post("/auth/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new farmer account and automatically geocode village/district if GPS is missing."""
    clean_username = req.username.strip().lower()
    if len(clean_username) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be at least 3 characters long.",
        )

    if len(req.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long.",
        )

    # Check for duplicate username
    existing_user = db.query(User).filter(User.username == clean_username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken. Please choose another username.",
        )

    lat = req.lat
    lon = req.lon
    village = req.village.strip() if req.village else None
    district = req.district.strip() if req.district else None
    state = req.state.strip() if req.state else None

    # Auto-geocode location if coordinates are not provided
    if lat is None or lon is None:
        candidates = [c for c in (village, district, state) if c]
        for place in candidates:
            query_name = place.split(",")[0].strip()
            if not query_name:
                continue
            try:
                geo_res = geocode_place(query_name)
                if isinstance(geo_res, dict) and "latitude" in geo_res and "longitude" in geo_res:
                    lat = geo_res["latitude"]
                    lon = geo_res["longitude"]
                    if not district and geo_res.get("district"):
                        district = geo_res["district"]
                    if not state and geo_res.get("state"):
                        state = geo_res["state"]
                    break
            except Exception:
                pass

    salt, pw_hash = hash_password(req.password)
    user = User(
        username=clean_username,
        password_hash=pw_hash,
        salt=salt,
        name=req.name.strip(),
        phone=req.phone.strip() if req.phone else None,
        language=req.language or "Marathi",
        village=village,
        district=district,
        state=state,
        lat=lat,
        lon=lon,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_session(db, user.id)
    profile = serialize_user(user)
    return {
        "status": "success",
        "token": token,
        "profile": profile,
        "user": profile,
    }


@router.post("/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate a farmer and return a session token."""
    clean_username = req.username.strip().lower()
    user = db.query(User).filter(User.username == clean_username).first()
    if not user or not verify_password(req.password, user.salt, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_session(db, user.id)
    profile = serialize_user(user)
    return {
        "status": "success",
        "token": token,
        "profile": profile,
        "user": profile,
    }


@router.post("/auth/logout")
def logout(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Log out by invalidating the active session token."""
    if credentials and credentials.credentials:
        delete_session(db, credentials.credentials)
    return {"status": "success", "message": "Logged out successfully."}


# ===================== Profile Endpoints =====================

@router.get("/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    """Retrieve the authenticated farmer's profile."""
    profile = serialize_user(current_user)
    # Return both top-level profile fields and nested for convenience
    return {**profile, "profile": profile}


@router.put("/profile")
def update_profile(
    req: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update profile details (language, village, district, state, coordinates)."""
    if req.name is not None:
        current_user.name = req.name.strip()
    if req.language is not None:
        current_user.language = req.language.strip()
    if req.phone is not None:
        current_user.phone = req.phone.strip() if req.phone else None
    if req.village is not None:
        current_user.village = req.village.strip() if req.village else None
    if req.district is not None:
        current_user.district = req.district.strip() if req.district else None
    if req.state is not None:
        current_user.state = req.state.strip() if req.state else None

    # Update coordinates if provided
    if req.lat is not None and req.lon is not None:
        current_user.lat = req.lat
        current_user.lon = req.lon
    elif current_user.lat is None or current_user.lon is None:
        # Try geocoding if coordinates are missing
        candidates = [c for c in (current_user.village, current_user.district, current_user.state) if c]
        for place in candidates:
            query_name = place.split(",")[0].strip()
            if not query_name:
                continue
            try:
                geo_res = geocode_place(query_name)
                if isinstance(geo_res, dict) and "latitude" in geo_res and "longitude" in geo_res:
                    current_user.lat = geo_res["latitude"]
                    current_user.lon = geo_res["longitude"]
                    break
            except Exception:
                pass

    db.commit()
    db.refresh(current_user)
    profile = serialize_user(current_user)
    return {**profile, "profile": profile}


@router.post("/profile/soil-refresh")
def refresh_soil(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch topsoil data (texture, pH, organic carbon) using coordinates from SoilGrids."""
    if current_user.lat is None or current_user.lon is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Farm coordinates (latitude and longitude) are required to fetch soil info. Please set your farm location first.",
        )

    try:
        soil_res = get_soil_info(current_user.lat, current_user.lon)
        if isinstance(soil_res, dict) and "error" not in soil_res:
            current_user.soil_texture = soil_res.get("texture_hint")
            current_user.soil_ph = soil_res.get("ph")
            current_user.soil_oc = soil_res.get("soc_g_per_kg")
            db.commit()
            db.refresh(current_user)
            profile = serialize_user(current_user)
            return {
                "status": "success",
                "soil": {
                    "texture": current_user.soil_texture,
                    "ph": current_user.soil_ph,
                    "oc": current_user.soil_oc,
                },
                "profile": profile,
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Soil data lookup failed: {soil_res.get('error', 'Unknown soil service response')}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to refresh soil data: {str(e)}",
        )


@router.post("/profile/telegram-link")
def generate_telegram_link_code(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a random 6-digit code for linking the farmer's Telegram account."""
    code = f"{secrets.randbelow(900000) + 100000}"
    current_user.link_code = code
    db.commit()
    db.refresh(current_user)

    bot_username = "KisanSathiBot"
    return {
        "status": "success",
        "link_code": code,
        "bot_username": bot_username,
        "command": f"/link {code}",
        "instructions": f"Open Telegram, start @{bot_username}, and send: /link {code}",
    }
