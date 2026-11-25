"""Background scheduler for daily farm briefings and periodic climate checks.

Implements APScheduler jobs for daily morning briefings and 3-hour climate checks,
resilient per-user error handling, and timezone-aware triggers.
"""

import logging
import re
from datetime import date
from zoneinfo import ZoneInfo
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.climate_watch import check_user
from app.config import settings
from app.db import SessionLocal
from app.models import Crop, User, WateringLog
from app.notify import create_notification, localise_text
from app.planner import calculate_risk_score, fertiliser_guidance, irrigation_decision
from app.weather import apply_demo, get_forecast

logger = logging.getLogger("kisansathi.scheduler")

_scheduler: Optional[BackgroundScheduler] = None


def generate_morning_briefing(user: User, db: Session) -> str:
    """Generate a concise daily morning briefing of at most 6 short lines in user's language.

    Contains no markdown symbols (*, _, #) for clean display and text-to-speech readability.
    """
    today = date.today()
    today_str = today.isoformat()

    # 1. Weather info
    forecast = []
    if user.lat is not None and user.lon is not None:
        try:
            forecast = get_forecast(user.lat, user.lon)
            if user.demo_scenario:
                forecast = apply_demo(forecast, user.demo_scenario)
        except Exception:
            forecast = []

    today_weather = next((d for d in forecast if d.get("date") == today_str), None)
    if not today_weather and forecast:
        today_weather = forecast[0]

    tmax = today_weather.get("tmax", 31.0) if today_weather else 31.0
    tmin = today_weather.get("tmin", 19.0) if today_weather else 19.0
    rain = today_weather.get("rain_mm", 0.0) if today_weather else 0.0
    prob = today_weather.get("rain_prob", 0) if today_weather else 0

    loc_name = user.village or user.district or "your farm"

    # 2. Crop details
    active_crop = (
        db.query(Crop)
        .filter(Crop.user_id == user.id, Crop.status == "active")
        .order_by(Crop.id.desc())
        .first()
    )

    lines = []
    # Line 1: Polite personal greeting
    lines.append(f"Namaste {user.name} ji, good morning from KisanSathi.")

    # Line 2: Today's weather
    lines.append(f"Weather for {loc_name}: max {tmax}°C, min {tmin}°C, rain {rain} mm ({prob}% chance).")

    if active_crop:
        days_elapsed = (today - active_crop.sowing_date).days if active_crop.sowing_date else 0
        irr = irrigation_decision(active_crop, user, forecast)
        fert = fertiliser_guidance(active_crop, user)
        risk = calculate_risk_score(active_crop, user, forecast, irr)

        stage_name = irr.get("stage", "Growth")
        # Line 3: Crop & Stage
        lines.append(f"{active_crop.crop} is in {stage_name} stage, Day {days_elapsed} since sowing.")

        # Line 4: Watering recommendation with litres
        if irr.get("water_today"):
            lines.append(f"Watering today: Yes, apply {irr.get('litres', 0):,} litres ({irr.get('mm', 0)} mm).")
        else:
            lines.append(f"Watering today: No, soil moisture is adequate (deficit {irr.get('deficit', 0)} mm).")
            # Automatically record skipped water when engine advises no watering needed
            # Rainfed crops never log saved water (rely solely on rainfall)
            is_rainfed = (active_crop.irrigation_type or "").lower() == "rainfed"
            if not is_rainfed:
                existing_log = db.query(WateringLog).filter(
                    WateringLog.crop_id == active_crop.id,
                    WateringLog.date == today,
                ).first()
                if not existing_log:
                    log_entry = WateringLog(
                        crop_id=active_crop.id,
                        date=today,
                        action="skipped",
                        mm_applied=0.0,
                        mm_saved=8.3,
                    )
                    db.add(log_entry)
                    db.commit()

        # Line 5: One concise fertiliser tip (pick first sentence only, no mid-word truncation)
        first_fert_block = fert.split("\n")[0].replace("Stage (", "").replace("):", " -").strip()
        fert_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", first_fert_block) if s.strip()]
        fert_tip = fert_sentences[0] if fert_sentences else first_fert_block
        if not fert_tip.endswith((".", "!", "?")):
            fert_tip += "."
        lines.append(f"Fertiliser tip: {fert_tip}")

        # Line 6: Risk score (first sentence of top reason, no mid-word truncation)
        top_reason = risk.get("reasons", ["Conditions stable"])[0].strip()
        reason_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", top_reason) if s.strip()]
        clean_reason = reason_sentences[0] if reason_sentences else top_reason
        if clean_reason.endswith((".", "!", "?")):
            clean_reason = clean_reason[:-1].strip()
        lines.append(f"Farm Risk: {risk.get('level', 'Good')} ({clean_reason}).")
    else:
        # Fallback lines if no crop is active yet
        lines.append("No active crops currently registered in your farm profile.")
        lines.append("Add a crop in My Crops to receive custom irrigation and nutrient advice.")
        lines.append("Soil test reminder: Maintain organic manure for healthy soil.")
        lines.append("Farm Risk: Good (All systems ready).")

    # Limit to at most 6 lines
    lines = lines[:6]
    english_briefing = "\n".join(lines)

    # Clean markdown
    english_briefing = (
        english_briefing.replace("*", "")
        .replace("#", "")
        .replace("`", "")
        .replace("_", "")
    )

    lang = user.language or "English"
    if lang.lower() not in ("english", "en", "auto"):
        briefing_text = localise_text(english_briefing, lang)
        # Clean any markdown symbols from translation
        briefing_text = (
            briefing_text.replace("*", "")
            .replace("#", "")
            .replace("`", "")
            .replace("_", "")
        )
    else:
        briefing_text = english_briefing

    # Enforce at most 6 lines after translation as well
    out_lines = [l.strip() for l in briefing_text.split("\n") if l.strip()]
    if len(out_lines) > 6:
        out_lines = out_lines[:6]
    final_briefing = "\n".join(out_lines)

    # Persist as notification (deduplicated by day)
    dedupe = f"briefing:{today_str}:{user.id}"
    create_notification(
        db,
        user,
        kind="briefing",
        severity="info",
        title="Daily Farm Briefing",
        body=final_briefing,
        dedupe_key=dedupe,
    )

    return final_briefing


def run_morning_briefings_job():
    """Trigger morning briefings for all farmers with active crops."""
    logger.info("Starting scheduled morning briefing job...")
    db = SessionLocal()
    try:
        users = db.query(User).all()
        for user in users:
            try:
                # Only farmers with at least one active crop
                active_crops = db.query(Crop).filter(Crop.user_id == user.id, Crop.status == "active").all()
                if active_crops:
                    generate_morning_briefing(user, db)

                    # Also evaluate all active irrigated crops for skipped water logging (upsert rule)
                    forecast = []
                    if user.lat is not None and user.lon is not None:
                        try:
                            forecast = get_forecast(user.lat, user.lon)
                            if user.demo_scenario:
                                forecast = apply_demo(forecast, user.demo_scenario)
                        except Exception:
                            forecast = []

                    today = date.today()
                    for c in active_crops:
                        if (c.irrigation_type or "").lower() != "rainfed":
                            c_irr = irrigation_decision(c, user, forecast)
                            if not c_irr.get("water_today"):
                                ex_log = db.query(WateringLog).filter(
                                    WateringLog.crop_id == c.id,
                                    WateringLog.date == today,
                                ).first()
                                if not ex_log:
                                    db.add(WateringLog(
                                        crop_id=c.id,
                                        date=today,
                                        action="skipped",
                                        mm_applied=0.0,
                                        mm_saved=8.3,
                                    ))
                                    db.commit()
            except Exception as e:
                logger.error("Failed morning briefing for user %s: %s", user.username, e)
    finally:
        db.close()
    logger.info("Morning briefing job finished.")


def run_climate_watch_job():
    """Trigger climate monitoring checks for all farmers with geographic coordinates."""
    logger.info("Starting scheduled 3-hour climate watch check...")
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.lat.isnot(None), User.lon.isnot(None)).all()
        for user in users:
            try:
                check_user(user, db)
            except Exception as e:
                logger.error("Failed climate watch check for user %s: %s", user.username, e)
    finally:
        db.close()
    logger.info("Climate watch job finished.")


def start_scheduler():
    """Start the APScheduler background daemon if RUN_SCHEDULER is enabled."""
    global _scheduler
    if not settings.run_scheduler:
        logger.info("RUN_SCHEDULER is false. Scheduler will not start.")
        return None

    if _scheduler is not None and _scheduler.running:
        return _scheduler

    try:
        tz = ZoneInfo(settings.app_timezone)
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")

    _scheduler = BackgroundScheduler(timezone=tz)

    # Daily morning briefing cron trigger
    _scheduler.add_job(
        run_morning_briefings_job,
        trigger=CronTrigger(
            hour=settings.morning_hour,
            minute=settings.morning_minute,
            timezone=tz,
        ),
        id="daily_morning_briefing",
        name="Daily Morning Farm Briefing",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )

    # 3-hour climate watch interval trigger
    _scheduler.add_job(
        run_climate_watch_job,
        trigger=IntervalTrigger(hours=3),
        id="climate_watch_3h",
        name="3-Hour Extreme Climate Watch",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("APScheduler started successfully for timezone %s.", settings.app_timezone)
    return _scheduler


def stop_scheduler():
    """Shut down the background scheduler if active."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("APScheduler stopped.")
