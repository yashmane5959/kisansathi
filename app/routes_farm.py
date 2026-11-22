"""Farm management and authenticated REST routes for KisanSathi."""

import secrets
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import create_user_session, delete_user_session, get_current_user, hash_password, verify_password
from app.db import get_db
from app.models import User
from app.tools import geocode_place, get_soil_info

router = APIRouter()


# ---------------------------------------------------------
# Schemas
# ---------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6)
    name: str = Field(..., min_length=1)
    language: str = "Marathi"
    village: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


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
    soil_texture: Optional[str] = None
    soil_ph: Optional[float] = None
    soil_oc: Optional[float] = None
    telegram_chat_id: Optional[str] = None


def user_to_dict(user: User) -> dict:
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
        "demo_scenario": user.demo_scenario,
    }


# ---------------------------------------------------------
# Authentication Routes
# ---------------------------------------------------------

@router.post("/auth/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    uname = req.username.strip().lower()
    existing = db.query(User).filter(User.username == uname).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already taken. Please choose another username.",
        )

    lat = req.lat
    lon = req.lon
    state = req.state
    district = req.district

    # If GPS not provided, attempt geocoding
    if (lat is None or lon is None) and (req.village or req.district):
        place_query = req.village or req.district
        geo = geocode_place(place_query)
        if "error" not in geo and "latitude" in geo and "longitude" in geo:
            lat = geo["latitude"]
            lon = geo["longitude"]
            state = state or geo.get("state")
            district = district or geo.get("district")

    pw_hash, salt = hash_password(req.password)
    new_user = User(
        username=uname,
        password_hash=pw_hash,
        salt=salt,
        name=req.name.strip(),
        language=req.language or "Marathi",
        village=req.village,
        district=district,
        state=state,
        lat=lat,
        lon=lon,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token = create_user_session(db, new_user.id)
    return {
        "token": token,
        "user": user_to_dict(new_user),
    }


@router.post("/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    uname = req.username.strip().lower()
    user = db.query(User).filter(User.username == uname).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    if not verify_password(req.password, user.password_hash, user.salt):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    token = create_user_session(db, user.id)
    return {
        "token": token,
        "user": user_to_dict(user),
    }


@router.post("/auth/logout")
def logout(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
        delete_user_session(db, token)
    return {"message": "Logged out successfully"}


# ---------------------------------------------------------
# Profile Routes
# ---------------------------------------------------------

@router.get("/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    return user_to_dict(current_user)


@router.put("/profile")
def update_profile(
    req: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if req.name is not None:
        current_user.name = req.name.strip()
    if req.language is not None:
        current_user.language = req.language.strip()
    if req.village is not None:
        current_user.village = req.village.strip()
    if req.district is not None:
        current_user.district = req.district.strip()
    if req.state is not None:
        current_user.state = req.state.strip()
    if req.lat is not None:
        current_user.lat = req.lat
    if req.lon is not None:
        current_user.lon = req.lon
    if req.soil_texture is not None:
        current_user.soil_texture = req.soil_texture
    if req.soil_ph is not None:
        current_user.soil_ph = req.soil_ph
    if req.soil_oc is not None:
        current_user.soil_oc = req.soil_oc
    if req.telegram_chat_id is not None:
        current_user.telegram_chat_id = req.telegram_chat_id.strip()

    db.commit()
    db.refresh(current_user)
    return user_to_dict(current_user)


@router.post("/profile/soil-refresh")
def refresh_soil_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lat = current_user.lat
    lon = current_user.lon
    if lat is None or lon is None:
        if current_user.district or current_user.village:
            geo = geocode_place(current_user.village or current_user.district)
            if "latitude" in geo and "longitude" in geo:
                lat = geo["latitude"]
                lon = geo["longitude"]
                current_user.lat = lat
                current_user.lon = lon

    if lat is None or lon is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Farm location coordinates (lat/lon) or district required to fetch soil info.",
        )

    soil = get_soil_info(lat, lon)
    current_user.soil_texture = soil.get("texture_hint", "loamy")
    current_user.soil_ph = soil.get("ph")
    current_user.soil_oc = soil.get("soc_g_per_kg")

    db.commit()
    db.refresh(current_user)
    return {
        "message": "Soil profile refreshed successfully.",
        "soil": soil,
        "profile": user_to_dict(current_user),
    }


@router.post("/profile/telegram-link")
def create_telegram_link(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Generate 6-digit link code
    code = str(secrets.randbelow(900000) + 100000)
    current_user.link_code = code
    db.commit()

    return {
        "link_code": code,
        "bot_username": "kisansathi01bot",
        "command": f"/link {code}",
        "instructions": f"Open Telegram, search for @kisansathi01bot, and send: /link {code}",
    }
