"""Weather forecast integration with Open-Meteo including ET0 and past history.

Implements in-memory 30-minute caching, robust timeout handling, and demo scenario overrides.
"""

import copy
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import urllib.request
import json

logger = logging.getLogger("kisansathi.weather")

# In-memory cache: (round_lat, round_lon) -> (timestamp, days_data)
_WEATHER_CACHE: Dict[Tuple[float, float], Tuple[float, List[Dict[str, Any]]]] = {}
CACHE_TTL_SECONDS = 1800  # 30 minutes


def _fetch_from_open_meteo(lat: float, lon: float, timeout: float = 20.0) -> Dict[str, Any]:
    """Execute raw HTTP request to Open-Meteo forecast API."""
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,et0_fao_evapotranspiration",
        "timezone": "auto",
        "past_days": 7,
        "forecast_days": 7,
    }
    url = f"https://api.open-meteo.com/v1/forecast?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "KisanSathi-Agritech-Advisor/2.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _build_fallback_forecast(today: date) -> List[Dict[str, Any]]:
    """Build a synthetic 14-day baseline forecast (-7 to +7 days) if external API is unreachable."""
    days = []
    today_str = today.isoformat()
    for offset in range(-7, 7):
        d = today + timedelta(days=offset)
        d_str = d.isoformat()
        days.append({
            "date": d_str,
            "tmax": 32.0,
            "tmin": 20.0,
            "rain_mm": 0.0,
            "rain_prob": 10,
            "et0": 4.5,
            "is_past": d_str < today_str,
        })
    return days


def get_forecast(lat: float, lon: float) -> List[Dict[str, Any]]:
    """Retrieve 14-day forecast (-7 past days to +7 forecast days) including FAO-56 ET0.

    Results are cached in memory for 30 minutes per coordinate pair.
    """
    cache_key = (round(lat, 3), round(lon, 3))
    now = time.time()
    today_str = date.today().isoformat()

    # Check cache freshness
    if cache_key in _WEATHER_CACHE:
        cached_time, cached_data = _WEATHER_CACHE[cache_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            return copy.deepcopy(cached_data)

    try:
        raw = _fetch_from_open_meteo(lat, lon)
        daily = raw.get("daily", {})
        times = daily.get("time", [])
        tmaxs = daily.get("temperature_2m_max", [])
        tmins = daily.get("temperature_2m_min", [])
        rains = daily.get("precipitation_sum", [])
        probs = daily.get("precipitation_probability_max", [])
        et0s = daily.get("et0_fao_evapotranspiration", [])

        days: List[Dict[str, Any]] = []
        for i in range(len(times)):
            day_str = times[i]
            tmax = float(tmaxs[i]) if i < len(tmaxs) and tmaxs[i] is not None else 32.0
            tmin = float(tmins[i]) if i < len(tmins) and tmins[i] is not None else 20.0
            rain = float(rains[i]) if i < len(rains) and rains[i] is not None else 0.0
            prob = int(probs[i]) if i < len(probs) and probs[i] is not None else 0
            et0 = float(et0s[i]) if i < len(et0s) and et0s[i] is not None else 4.5

            days.append({
                "date": day_str,
                "tmax": round(tmax, 1),
                "tmin": round(tmin, 1),
                "rain_mm": round(rain, 1),
                "rain_prob": prob,
                "et0": round(et0, 2),
                "is_past": day_str < today_str,
            })

        if days:
            _WEATHER_CACHE[cache_key] = (now, days)
            return copy.deepcopy(days)

    except Exception as e:
        logger.warning("Forecast fetch failed for (%s, %s): %s", lat, lon, e)
        # If we have stale cache, use it
        if cache_key in _WEATHER_CACHE:
            _, stale_data = _WEATHER_CACHE[cache_key]
            return copy.deepcopy(stale_data)

    # Clean fallback if API and cache are unavailable
    return _build_fallback_forecast(date.today())


def apply_demo(days: List[Dict[str, Any]], scenario: Optional[str]) -> List[Dict[str, Any]]:
    """Override the next 3 future days with simulated scenario values.

    Never modifies original cache data; returns an altered deep copy.
    Scenarios:
      - 'heatwave': tmax = 44.0°C
      - 'heavyrain': rain_mm = 90.0mm, rain_prob = 95%
      - 'frost': tmin = 2.0°C
      - 'clear': rain_mm = 0.0mm, rain_prob = 0%
    """
    days_copy = copy.deepcopy(days)
    if not scenario or scenario.lower() not in ("heatwave", "heavyrain", "frost", "clear"):
        return days_copy

    scenario = scenario.lower()
    today_str = date.today().isoformat()

    # Find the next 3 upcoming future/today days
    future_count = 0
    for day in days_copy:
        if day["date"] >= today_str:
            if scenario == "heatwave":
                day["tmax"] = 44.0
            elif scenario == "heavyrain":
                day["rain_mm"] = 90.0
                day["rain_prob"] = 95
            elif scenario == "frost":
                day["tmin"] = 2.0
            elif scenario == "clear":
                day["rain_mm"] = 0.0
                day["rain_prob"] = 0

            future_count += 1
            if future_count >= 3:
                break

    return days_copy
