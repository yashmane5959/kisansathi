"""FastAPI Web and API server for KisanSathi."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent import advise, diagnose_crop_disease
from app.alerts import detect_risks
from app.config import settings
from app.db import Base, engine, init_db
from app.routes_farm import router as farm_router

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
STATIC_DIR = WEB_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables exist
    init_db()
    yield
    # Shutdown logic if any


app = FastAPI(
    title="KisanSathi API",
    description="Multilingual AI Agricultural Advisor & Farm Management Platform",
    version="2.0.0",
    lifespan=lifespan,
)

# Enable CORS for frontend and external clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mount farm routes
app.include_router(farm_router, prefix="/api")


class AdviseRequest(BaseModel):
    text: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    district: Optional[str] = None
    language: Optional[str] = "auto"


class AdviseResponse(BaseModel):
    answer: str


class AlertResponse(BaseModel):
    risks: List[str]


@app.get("/")
def serve_root():
    """Forward root to login page."""
    login_path = WEB_DIR / "login.html"
    if login_path.exists():
        return FileResponse(str(login_path))
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "KisanSathi is running."}


@app.get("/login")
def serve_login():
    """Serve login and registration page."""
    login_path = WEB_DIR / "login.html"
    if login_path.exists():
        return FileResponse(str(login_path))
    return RedirectResponse(url="/")


@app.get("/dashboard")
def serve_dashboard():
    """Serve the farm dashboard page."""
    dashboard_path = WEB_DIR / "dashboard.html"
    if dashboard_path.exists():
        return FileResponse(str(dashboard_path))
    return RedirectResponse(url="/")


@app.get("/chat")
def serve_chat():
    """Serve the original standalone KisanSathi chat advisor."""
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Chat page not found."}


@app.post("/api/advise", response_model=AdviseResponse)
def advise_text_endpoint(req: AdviseRequest):
    """Sync endpoint for text advice so FastAPI executes the blocking Gemini agent in a threadpool."""
    try:
        ans = advise(
            text=req.text,
            lat=req.lat,
            lon=req.lon,
            district=req.district,
            language=req.language or "auto",
        )
        return AdviseResponse(answer=ans)
    except Exception as e:
        return AdviseResponse(
            answer=f"Namaste farmer friend, we experienced a temporary issue: {str(e)}. Please check your connection or try again."
        )


@app.post("/api/advise-audio", response_model=AdviseResponse)
async def advise_audio_endpoint(
    audio_file: UploadFile = File(...),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
    district: Optional[str] = Form(None),
    language: Optional[str] = Form("auto"),
):
    """Multipart endpoint for voice queries."""
    try:
        content = await audio_file.read()
        mime_type = audio_file.content_type or "audio/ogg"
        # Run synchronous advise in threadpool
        ans = await asyncio.to_thread(
            advise,
            text=None,
            audio=content,
            audio_mime=mime_type,
            lat=lat,
            lon=lon,
            district=district,
            language=language or "auto",
        )
        return AdviseResponse(answer=ans)
    except Exception as e:
        return AdviseResponse(
            answer=f"Could not process voice message: {str(e)}. Please try asking with text."
        )


@app.get("/api/alerts", response_model=AlertResponse)
def get_alerts_endpoint(
    lat: float = Query(..., description="Latitude of the farm"),
    lon: float = Query(..., description="Longitude of the farm"),
):
    """Check for high-risk agricultural weather alerts (heavy rain, heatwave, cold night)."""
    try:
        risks = detect_risks(lat=lat, lon=lon)
        return AlertResponse(risks=risks)
    except Exception:
        return AlertResponse(risks=[])


@app.post("/api/diagnose-crop", response_model=AdviseResponse)
async def diagnose_crop_endpoint(
    image: UploadFile = File(...),
    notes: Optional[str] = Form(None),
    language: Optional[str] = Form("auto"),
):
    """Multimodal crop disease and pest diagnosis via uploaded leaf/crop photograph."""
    try:
        content = await image.read()
        mime_type = image.content_type or "image/jpeg"
        ans = await asyncio.to_thread(
            diagnose_crop_disease,
            image_bytes=content,
            image_mime=mime_type,
            notes=notes,
            language=language or "auto",
        )
        return AdviseResponse(answer=ans)
    except Exception as e:
        return AdviseResponse(
            answer=f"Could not analyze crop photo: {str(e)}. Please try again."
        )


@app.get("/api/health")
def health_check():
    """Health check endpoint to inspect system readiness and keys."""
    return {
        "status": "healthy",
        "model": settings.gemini_model,
        "gemini_key_set": bool(settings.gemini_api_key),
        "data_gov_key_set": bool(settings.data_gov_api_key),
        "telegram_bot_configured": bool(settings.telegram_bot_token),
    }
