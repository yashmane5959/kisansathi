"""API routes for authentication, farm profiles, and user management."""

import json
import secrets
from datetime import date
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
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
from app.crop_data import SUPPORTED_CROPS, get_crop_data
from app.db import get_db
from app.models import Crop, Notification, User, WateringLog
from app.planner import (
    build_roadmap,
    calculate_overall_risk,
    calculate_risk_score,
    fertiliser_guidance,
    irrigation_decision,
    localise_roadmap,
)
from app.tools import geocode_place, get_soil_info
from app.weather import get_forecast

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


def serialize_crop(crop: Crop) -> Dict[str, Any]:
    """Helper to convert a Crop model instance into a JSON-friendly dict."""
    stages = []
    if crop.roadmap_json:
        try:
            stages = json.loads(crop.roadmap_json)
        except Exception:
            stages = []
    return {
        "id": crop.id,
        "user_id": crop.user_id,
        "crop": crop.crop,
        "area_acres": crop.area_acres,
        "sowing_date": crop.sowing_date.isoformat() if crop.sowing_date else None,
        "irrigation_type": crop.irrigation_type,
        "last_watered": crop.last_watered.isoformat() if crop.last_watered else None,
        "status": crop.status,
        "roadmap_lang": crop.roadmap_lang,
        "stages": stages,
        "created_at": crop.created_at.isoformat() if crop.created_at else None,
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


class CreateCropRequest(BaseModel):
    crop: str = Field(..., description="Crop name (e.g. Onion, Tomato, Wheat, Soybean, Cotton, Rice, Sugarcane)")
    area_acres: float = Field(1.0, gt=0, description="Field area in acres")
    sowing_date: date = Field(..., description="Date of sowing or transplanting (YYYY-MM-DD)")
    irrigation_type: str = Field("drip", description="Irrigation method: 'rainfed', 'drip', or 'flood'")


class WateredRequest(BaseModel):
    action: Optional[str] = "watered"  # "watered" or "skipped"
    mm: Optional[float] = None


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


# ===================== Crop Endpoints =====================

@router.get("/crops")
def list_crops(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all crops belonging to the authenticated farmer."""
    crops = db.query(Crop).filter(Crop.user_id == current_user.id).order_by(Crop.id.desc()).all()
    return [serialize_crop(c) for c in crops]


@router.post("/crops")
def create_crop(
    req: CreateCropRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a new crop to the farmer's portfolio and build its growth roadmap."""
    crop_info = get_crop_data(req.crop)
    if not crop_info:
        valid_crops = ", ".join(SUPPORTED_CROPS)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported crop '{req.crop}'. Supported crops are: {valid_crops}.",
        )

    canonical_crop = crop_info["canonical_name"]
    irrigation = req.irrigation_type.strip().lower()
    if irrigation not in ("rainfed", "drip", "flood"):
        irrigation = "drip"

    # Fetch weather forecast for weather warnings if coordinates are available
    forecast_days = None
    if current_user.lat is not None and current_user.lon is not None:
        try:
            forecast_days = get_forecast(current_user.lat, current_user.lon)
        except Exception:
            forecast_days = None

    class CropContext:
        crop = canonical_crop
        sowing_date = req.sowing_date
        area_acres = req.area_acres
        irrigation_type = irrigation

    english_stages = build_roadmap(CropContext(), forecast_days=forecast_days)

    target_lang = current_user.language or "English"
    if target_lang.lower() not in ("english", "en", "auto"):
        stages = localise_roadmap(english_stages, target_lang)
        roadmap_lang = target_lang
    else:
        stages = english_stages
        roadmap_lang = "English"

    crop = Crop(
        user_id=current_user.id,
        crop=canonical_crop,
        area_acres=req.area_acres,
        sowing_date=req.sowing_date,
        irrigation_type=irrigation,
        status="active",
        roadmap_json=json.dumps(stages, ensure_ascii=False),
        roadmap_lang=roadmap_lang,
    )
    db.add(crop)
    db.commit()
    db.refresh(crop)

    return serialize_crop(crop)


@router.delete("/crops/{crop_id}")
def delete_crop(
    crop_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a crop from the farmer's portfolio. Only the crop owner can delete."""
    crop = db.query(Crop).filter(Crop.id == crop_id, Crop.user_id == current_user.id).first()
    if not crop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crop not found or you do not have permission to delete it.",
        )

    db.delete(crop)
    db.commit()
    return {"status": "success", "message": f"Crop {crop_id} deleted successfully."}


@router.get("/crops/{crop_id}/roadmap")
def get_crop_roadmap(
    crop_id: int,
    lang: Optional[str] = Query(None, description="Language for roadmap localisation (e.g. Marathi, Hindi)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve dated roadmap for a specific crop, optionally localised to a chosen language."""
    crop = db.query(Crop).filter(Crop.id == crop_id, Crop.user_id == current_user.id).first()
    if not crop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crop not found or you do not have permission to access it.",
        )

    target_lang = lang.strip() if lang and lang.strip() else (current_user.language or "English")

    # If already cached in target language, return directly
    if crop.roadmap_json and crop.roadmap_lang and crop.roadmap_lang.lower() == target_lang.lower():
        try:
            cached_stages = json.loads(crop.roadmap_json)
            return {
                "crop_id": crop.id,
                "crop": crop.crop,
                "language": crop.roadmap_lang,
                "stages": cached_stages,
            }
        except Exception:
            pass

    # Build fresh English stages
    forecast_days = None
    if current_user.lat is not None and current_user.lon is not None:
        try:
            forecast_days = get_forecast(current_user.lat, current_user.lon)
        except Exception:
            forecast_days = None

    english_stages = build_roadmap(crop, forecast_days=forecast_days)

    if target_lang.lower() not in ("english", "en", "auto"):
        localised_stages = localise_roadmap(english_stages, target_lang)
        crop.roadmap_json = json.dumps(localised_stages, ensure_ascii=False)
        crop.roadmap_lang = target_lang
        db.commit()
        return {
            "crop_id": crop.id,
            "crop": crop.crop,
            "language": target_lang,
            "stages": localised_stages,
        }
    else:
        crop.roadmap_json = json.dumps(english_stages, ensure_ascii=False)
        crop.roadmap_lang = "English"
        db.commit()
        return {
            "crop_id": crop.id,
            "crop": crop.crop,
            "language": "English",
            "stages": english_stages,
        }


@router.post("/crops/{crop_id}/watered")
def record_watering_event(
    crop_id: int,
    req: Optional[WateredRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Log an irrigation event or skipped watering, update last_watered, and record saved water."""
    crop = db.query(Crop).filter(Crop.id == crop_id, Crop.user_id == current_user.id).first()
    if not crop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crop not found or you do not have permission to log watering for it.",
        )

    action = (req.action or "watered").strip().lower() if req else "watered"
    today = date.today()

    if action == "watered":
        crop.last_watered = today
        applied_mm = float(req.mm) if (req and req.mm is not None) else 25.0
        saved_mm = 0.0
        log_entry = WateringLog(
            crop_id=crop.id,
            date=today,
            action="watered",
            mm_applied=applied_mm,
            mm_saved=saved_mm,
        )
        db.add(log_entry)
        db.commit()
        db.refresh(crop)
        message = f"Recorded watering of {applied_mm} mm for crop {crop.crop}."
    else:  # skipped
        applied_mm = 0.0
        saved_mm = float(req.mm) if (req and req.mm is not None) else 25.0
        log_entry = WateringLog(
            crop_id=crop.id,
            date=today,
            action="skipped",
            mm_applied=applied_mm,
            mm_saved=saved_mm,
        )
        db.add(log_entry)
        db.commit()
        message = f"Recorded skipped watering of {saved_mm} mm for crop {crop.crop}."

    return {
        "status": "success",
        "crop_id": crop.id,
        "crop": crop.crop,
        "last_watered": crop.last_watered.isoformat() if crop.last_watered else None,
        "action": action,
        "mm_applied": applied_mm,
        "mm_saved": saved_mm,
        "message": message,
    }


# ===================== Today Dashboard Endpoint =====================

@router.get("/today")
def get_today_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve the unified daily farm dashboard: weather, per-crop advice, irrigation, risk, and water saved."""
    today = date.today()
    today_str = today.isoformat()

    # 1. Weather forecast
    forecast_days = []
    weather_summary = {}
    if current_user.lat is not None and current_user.lon is not None:
        try:
            forecast_days = get_forecast(current_user.lat, current_user.lon)
            today_weather = next((d for d in forecast_days if d.get("date") == today_str), None)
            if not today_weather and forecast_days:
                today_weather = forecast_days[0]

            future_strip = [d for d in forecast_days if d.get("date") and d["date"] >= today_str][:7]
            weather_summary = {
                "location": {
                    "village": current_user.village,
                    "district": current_user.district,
                    "state": current_user.state,
                    "lat": current_user.lat,
                    "lon": current_user.lon,
                },
                "today": today_weather,
                "forecast_7d": future_strip,
            }
        except Exception:
            weather_summary = {"notice": "Weather forecast temporarily unavailable."}
    else:
        weather_summary = {"notice": "Farm location coordinates not set."}

    # 2. Crops evaluation
    crops = db.query(Crop).filter(Crop.user_id == current_user.id, Crop.status == "active").all()
    crop_cards = []
    crop_risks = []

    for c in crops:
        days_since_sowing = (today - c.sowing_date).days if c.sowing_date else 0

        # Irrigation recommendation
        irr = irrigation_decision(c, current_user, forecast_days)

        # Fertiliser guidance
        fert = fertiliser_guidance(c, current_user)

        # Risk score for this crop
        risk = calculate_risk_score(c, current_user, forecast_days, irr)
        crop_risks.append(risk)

        crop_cards.append({
            "id": c.id,
            "crop": c.crop,
            "area_acres": c.area_acres,
            "irrigation_type": c.irrigation_type,
            "sowing_date": c.sowing_date.isoformat() if c.sowing_date else None,
            "days_since_sowing": days_since_sowing,
            "last_watered": c.last_watered.isoformat() if c.last_watered else None,
            "current_stage": irr.get("stage", "Growth"),
            "irrigation": irr,
            "fertiliser": fert,
            "risk": risk,
        })

    # 3. Overall farm risk
    overall_risk = calculate_overall_risk(crop_risks)

    # 4. Total water saved calculation
    water_logs = (
        db.query(WateringLog, Crop.area_acres)
        .join(Crop, WateringLog.crop_id == Crop.id)
        .filter(Crop.user_id == current_user.id)
        .all()
    )
    total_mm_saved = sum(log.mm_saved for log, _ in water_logs)
    total_litres_saved = sum(log.mm_saved * 4047.0 * float(area or 1.0) for log, area in water_logs)

    # 5. Unread notification count
    unread_count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.read == False)
        .count()
    )

    return {
        "user": serialize_user(current_user),
        "weather": weather_summary,
        "crops": crop_cards,
        "risk_score": overall_risk,
        "water_saved_total": {
            "litres": int(round(total_litres_saved)),
            "mm": round(total_mm_saved, 1),
        },
        "unread_notifications_count": unread_count,
    }
