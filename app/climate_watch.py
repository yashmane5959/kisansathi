"""Climate and extreme weather monitoring service for KisanSathi.

Evaluates multi-day forecasts against crop sensitivities, detects rapid weather
forecast swings, and triggers actionable notifications.
"""

import json
import logging
from datetime import date, datetime
from typing import List, Optional
from sqlalchemy.orm import Session

from app.crop_data import get_crop_data
from app.models import Crop, ForecastSnapshot, Notification, User
from app.notify import create_notification
from app.weather import apply_demo, get_forecast

logger = logging.getLogger("kisansathi.climate_watch")


def check_user(user: User, db: Session) -> List[Notification]:
    """Inspect user's location and active crops for severe weather conditions and forecast swings.

    Creates deduplicated danger and forecast-change notifications.
    """
    if user.lat is None or user.lon is None:
        return []

    # 1. Fetch forecast and apply demo scenario if active
    days = get_forecast(user.lat, user.lon)
    if user.demo_scenario:
        days = apply_demo(days, user.demo_scenario)

    today = date.today()
    today_str = today.isoformat()
    upcoming_3_days = [d for d in days if d.get("date") and d["date"] >= today_str][:3]
    if not upcoming_3_days:
        return []

    created_notifications: List[Notification] = []
    active_crops = db.query(Crop).filter(Crop.user_id == user.id, Crop.status == "active").all()

    # 2. Check each crop against sensitivity thresholds for next 3 days
    # Creates ONE danger notification per event type per crop naming the first affected day and duration
    if active_crops:
        for crop in active_crops:
            crop_info = get_crop_data(crop.crop)
            sens = crop_info.get("sensitivity", {}) if crop_info else {}
            heat_thresh = sens.get("heat_c", 40.0)
            cold_thresh = sens.get("cold_c", 6.0)
            rain_thresh = sens.get("heavy_rain_mm", 50.0)

            heat_days = [d for d in upcoming_3_days if float(d.get("tmax", 30.0)) >= heat_thresh]
            cold_days = [d for d in upcoming_3_days if float(d.get("tmin", 20.0)) <= cold_thresh]
            rain_days = [d for d in upcoming_3_days if float(d.get("rain_mm", 0.0)) >= rain_thresh]

            # 1. Heatwave: exactly ONE danger notification per crop
            if heat_days:
                first_d = heat_days[0]["date"]
                duration = len(heat_days)
                max_t = max(float(d.get("tmax", 30.0)) for d in heat_days)
                dedupe = f"climate:{first_d}:heatwave:{crop.id}"
                title = f"Heatwave Alert for {crop.crop}"
                if duration == 1:
                    body = (
                        f"Extreme temperature of {max_t:.1f}°C is forecast on {first_d}. "
                        f"Irrigate during evening hours, mulch around root zones, and avoid daytime pesticide spraying."
                    )
                else:
                    body = (
                        f"Heatwave lasting {duration} days starting {first_d} (peak temperature {max_t:.1f}°C). "
                        f"Irrigate during evening hours, mulch around root zones, and avoid daytime pesticide spraying."
                    )
                n = create_notification(
                    db, user, kind="climate", severity="danger",
                    title=title, body=body, dedupe_key=dedupe
                )
                if n:
                    created_notifications.append(n)

            # 2. Cold wave / frost: exactly ONE danger notification per crop
            if cold_days:
                first_d = cold_days[0]["date"]
                duration = len(cold_days)
                min_t = min(float(d.get("tmin", 20.0)) for d in cold_days)
                dedupe = f"climate:{first_d}:cold:{crop.id}"
                title = f"Cold Wave & Frost Warning for {crop.crop}"
                if duration == 1:
                    body = (
                        f"Severe night temperature drop to {min_t:.1f}°C is expected on {first_d}. "
                        f"Give a light evening irrigation to keep root zones warm and cover tender nursery beds."
                    )
                else:
                    body = (
                        f"Cold wave lasting {duration} days starting {first_d} (lowest temperature {min_t:.1f}°C). "
                        f"Give a light evening irrigation to keep root zones warm and cover tender nursery beds."
                    )
                n = create_notification(
                    db, user, kind="climate", severity="danger",
                    title=title, body=body, dedupe_key=dedupe
                )
                if n:
                    created_notifications.append(n)

            # 3. Heavy rain: exactly ONE danger notification per crop
            if rain_days:
                first_d = rain_days[0]["date"]
                duration = len(rain_days)
                max_rain = max(float(d.get("rain_mm", 0.0)) for d in rain_days)
                total_rain = sum(float(d.get("rain_mm", 0.0)) for d in rain_days)
                dedupe = f"climate:{first_d}:heavyrain:{crop.id}"
                title = f"Heavy Rainfall Warning for {crop.crop}"
                if duration == 1:
                    body = (
                        f"Heavy rain of {max_rain:.1f} mm is forecast on {first_d}. "
                        f"Clear field drainage furrows immediately; postpone all spraying, weeding, and fertilizer applications."
                    )
                else:
                    body = (
                        f"Heavy rainfall lasting {duration} days starting {first_d} (total {total_rain:.1f} mm, peak {max_rain:.1f} mm). "
                        f"Clear field drainage furrows immediately; postpone all spraying, weeding, and fertilizer applications."
                    )
                n = create_notification(
                    db, user, kind="climate", severity="danger",
                    title=title, body=body, dedupe_key=dedupe
                )
                if n:
                    created_notifications.append(n)
    else:
        # User has location but no crops: check generic agricultural thresholds
        heat_days = [d for d in upcoming_3_days if float(d.get("tmax", 30.0)) >= 40.0]
        rain_days = [d for d in upcoming_3_days if float(d.get("rain_mm", 0.0)) >= 50.0]

        if heat_days:
            first_d = heat_days[0]["date"]
            duration = len(heat_days)
            max_t = max(float(d.get("tmax", 30.0)) for d in heat_days)
            dedupe = f"climate:{first_d}:heatwave:0"
            if duration == 1:
                body = f"High temperature of {max_t:.1f}°C forecast on {first_d}. Ensure farm livestock and nursery are shaded."
            else:
                body = f"High temperature lasting {duration} days starting {first_d} (peak {max_t:.1f}°C). Ensure farm livestock and nursery are shaded."
            n = create_notification(
                db, user, kind="climate", severity="danger",
                title="High Temperature Warning",
                body=body,
                dedupe_key=dedupe,
            )
            if n:
                created_notifications.append(n)

        if rain_days:
            first_d = rain_days[0]["date"]
            duration = len(rain_days)
            max_rain = max(float(d.get("rain_mm", 0.0)) for d in rain_days)
            total_rain = sum(float(d.get("rain_mm", 0.0)) for d in rain_days)
            dedupe = f"climate:{first_d}:heavyrain:0"
            if duration == 1:
                body = f"Heavy rain of {max_rain:.1f} mm forecast on {first_d}. Secure farm drains and postpone spraying."
            else:
                body = f"Heavy rain lasting {duration} days starting {first_d} (total {total_rain:.1f} mm). Secure farm drains and postpone spraying."
            n = create_notification(
                db, user, kind="climate", severity="danger",
                title="Heavy Rain Warning",
                body=body,
                dedupe_key=dedupe,
            )
            if n:
                created_notifications.append(n)

    # 3. Detect sudden forecast changes vs. previous ForecastSnapshot
    rain_sum = round(sum(float(d.get("rain_mm", 0.0)) for d in upcoming_3_days), 1)
    tmax_peak = round(max((float(d.get("tmax", 30.0)) for d in upcoming_3_days), default=30.0), 1)
    tmin_dip = round(min((float(d.get("tmin", 20.0)) for d in upcoming_3_days), default=20.0), 1)
    current_summary = {"rain_mm": rain_sum, "tmax": tmax_peak, "tmin": tmin_dip}

    last_snapshot = (
        db.query(ForecastSnapshot)
        .filter(ForecastSnapshot.user_id == user.id)
        .order_by(ForecastSnapshot.id.desc())
        .first()
    )

    if last_snapshot and last_snapshot.summary_json:
        try:
            prev = json.loads(last_snapshot.summary_json)
            rain_diff = abs(rain_sum - float(prev.get("rain_mm", 0.0)))
            tmax_diff = abs(tmax_peak - float(prev.get("tmax", 30.0)))

            if rain_diff >= 20.0 or tmax_diff >= 4.0:
                dedupe_fc = f"forecast_change:{today_str}:{user.id}"
                change_reasons = []
                if rain_diff >= 20.0:
                    change_reasons.append(f"3-day rain changed by {rain_diff:.1f} mm")
                if tmax_diff >= 4.0:
                    change_reasons.append(f"max temperature shifted by {tmax_diff:.1f}°C")

                title = "Significant Weather Forecast Shift"
                body = (
                    f"Weather forecast has shifted ({', '.join(change_reasons)}). "
                    f"Please review your planned spraying, irrigation, and field work."
                )
                n = create_notification(
                    db, user, kind="forecast_change", severity="warning",
                    title=title, body=body, dedupe_key=dedupe_fc
                )
                if n:
                    created_notifications.append(n)
        except Exception as e:
            logger.warning("Error comparing forecast snapshot: %s", e)

    # Save new snapshot
    new_snapshot = ForecastSnapshot(
        user_id=user.id,
        taken_at=datetime.utcnow(),
        summary_json=json.dumps(current_summary),
    )
    db.add(new_snapshot)
    db.commit()

    return created_notifications
