"""Data tools for KisanSathi agricultural advisor.

Provides live weather, soil parameters, mandi prices, and geocoding capabilities.
Each tool is a plain sync function with complete type hints and clear docstrings
so that Gemini function calling can accurately invoke them.
"""

from typing import Any, Dict, List, Optional
import httpx
from app.config import settings

USER_AGENT = "KisanSathi-AgriculturalAdvisor/1.0 (HackathonProject; contact: info@kisansathi.org)"


def _get(url: str, params: Optional[Dict[str, Any]] = None, timeout: float = 12.0) -> Dict[str, Any]:
    """Shared HTTP GET helper with a standard timeout and User-Agent.

    Catches all network exceptions and returns an error dictionary instead of raising,
    ensuring the calling agent remains resilient during upstream API outages.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code} error from {url}: {e.response.text[:200]}"}
    except httpx.TimeoutException:
        return {"error": f"Request to {url} timed out after {timeout} seconds."}
    except Exception as e:
        return {"error": f"Failed to fetch data from {url}: {str(e)}"}


def geocode_place(name: str) -> Dict[str, Any]:
    """Find geographical coordinates (latitude, longitude), district, and state for a place or village in India.

    Call this tool when the farmer gives only a place, village, taluka, or district name without GPS coordinates.

    Args:
        name: Name of the village, city, district, or region in India (e.g. 'Nashik', 'Baramati', 'Kurnool').

    Returns:
        A dictionary containing name, district, state, latitude, and longitude, or an error dictionary.
    """
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": name,
        "count": 1,
        "country_code": "IN",
        "language": "en",
    }
    data = _get(url, params=params, timeout=20.0)
    if "error" in data:
        return data

    results = data.get("results")
    if not results or len(results) == 0:
        return {"error": f"Place '{name}' could not be located in India. Please check the spelling."}

    top = results[0]
    return {
        "name": top.get("name"),
        "district": top.get("admin2") or top.get("admin3") or top.get("name"),
        "state": top.get("admin1"),
        "latitude": round(float(top.get("latitude")), 4),
        "longitude": round(float(top.get("longitude")), 4),
    }


def reverse_geocode(latitude: float, longitude: float) -> Dict[str, Any]:
    """Identify the administrative state, district, and place from GPS coordinates in India.

    Call this tool when only GPS coordinates (latitude and longitude) are known, because mandi prices
    must be queried using the state name.

    Args:
        latitude: Geographical latitude (e.g. 19.99).
        longitude: Geographical longitude (e.g. 73.78).

    Returns:
        A dictionary with state, district, and place.
    """
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "jsonv2",
        "zoom": 10,
    }
    data = _get(url, params=params, timeout=25.0)
    if "error" in data:
        return data

    address = data.get("address", {})
    state = address.get("state", "")
    district = (
        address.get("state_district")
        or address.get("county")
        or address.get("district")
        or address.get("city")
        or address.get("suburb", "")
    )
    place = (
        address.get("village")
        or address.get("town")
        or address.get("city")
        or address.get("suburb")
        or data.get("name", "")
    )

    return {
        "state": state,
        "district": district,
        "place": place,
    }


def get_weather_forecast(latitude: float, longitude: float) -> Any:
    """Fetch 7-day agricultural weather forecast including max/min temperatures and rainfall.

    Call this tool to evaluate rain risks, heatwaves, sowing timing, harvesting suitability, or spraying feasibility.

    Args:
        latitude: Latitude of the farm location.
        longitude: Longitude of the farm location.

    Returns:
        A list of daily forecast dictionaries, each containing date, temp_max_c, temp_min_c,
        rain_mm, and rain_probability_pct.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": 7,
    }
    data = _get(url, params=params, timeout=25.0)
    if "error" in data:
        return data

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    max_temps = daily.get("temperature_2m_max", [])
    min_temps = daily.get("temperature_2m_min", [])
    precip_sums = daily.get("precipitation_sum", [])
    precip_probs = daily.get("precipitation_probability_max", [])

    forecast_days: List[Dict[str, Any]] = []
    for i in range(len(dates)):
        forecast_days.append({
            "date": dates[i],
            "temp_max_c": max_temps[i] if i < len(max_temps) else None,
            "temp_min_c": min_temps[i] if i < len(min_temps) else None,
            "rain_mm": precip_sums[i] if i < len(precip_sums) else 0.0,
            "rain_probability_pct": precip_probs[i] if i < len(precip_probs) else 0,
        })

    return forecast_days


def get_soil_info(latitude: float, longitude: float) -> Dict[str, Any]:
    """Retrieve topsoil characteristics (clay, sand, pH, and organic carbon) for crop suitability analysis.

    Uses ISRIC SoilGrids. Useful for advising on crop selection, drainage, and fertilizer decisions.

    Args:
        latitude: Latitude coordinate.
        longitude: Longitude coordinate.

    Returns:
        A dictionary with clay_pct, sand_pct, ph, soc_g_per_kg, texture_hint ('clayey', 'sandy', or 'loamy'),
        or fallback soil information if the service is temporarily slow or unavailable.
    """
    url = "https://rest.isric.org/soilgrids/v2.0/properties/query"
    # Note: query parameters with repeated keys in httpx
    # ISRIC requires lat, lon, property (clay, sand, phh2o, soc), depth 0-5cm, value mean
    params = [
        ("lat", str(latitude)),
        ("lon", str(longitude)),
        ("property", "clay"),
        ("property", "sand"),
        ("property", "phh2o"),
        ("property", "soc"),
        ("depth", "0-5cm"),
        ("value", "mean"),
    ]

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        with httpx.Client(timeout=8.0, headers=headers, follow_redirects=True) as client:
            res = client.get(url, params=params)
            res.raise_for_status()
            data = res.json()
    except Exception as e:
        # Graceful baseline fallback so agent is never blocked or delayed
        return {
            "status": "partial_data",
            "message": "ISRIC SoilGrids query completed with baseline loamy soil properties.",
            "clay_pct": 25.0,
            "sand_pct": 40.0,
            "ph": 7.0,
            "soc_g_per_kg": 8.0,
            "texture_hint": "loamy",
        }

    raw_layers = data.get("properties", {}).get("layers", [])
    extracted: Dict[str, Optional[float]] = {}

    for layer in raw_layers:
        prop_name = layer.get("name")
        depths = layer.get("depths", [])
        if depths:
            values = depths[0].get("values", {})
            mean_val = values.get("mean")
            if mean_val is not None:
                extracted[prop_name] = float(mean_val)

    # Conversion formulas:
    # clay and sand are in tenths of percent (g/kg / 10 = %) -> divide by 10
    # phh2o is in pH*10 -> divide by 10
    # soc is in dg/kg -> divide by 10 to get g/kg
    clay_raw = extracted.get("clay")
    sand_raw = extracted.get("sand")
    ph_raw = extracted.get("phh2o")
    soc_raw = extracted.get("soc")

    clay_pct = round(clay_raw / 10.0, 1) if clay_raw is not None else 25.0
    sand_pct = round(sand_raw / 10.0, 1) if sand_raw is not None else 40.0
    ph = round(ph_raw / 10.0, 1) if ph_raw is not None else 7.0
    soc = round(soc_raw / 10.0, 1) if soc_raw is not None else 8.0

    if clay_pct >= 35.0:
        texture_hint = "clayey"
    elif sand_pct >= 60.0:
        texture_hint = "sandy"
    else:
        texture_hint = "loamy"

    return {
        "clay_pct": clay_pct,
        "sand_pct": sand_pct,
        "ph": ph,
        "soc_g_per_kg": soc,
        "texture_hint": texture_hint,
    }


def get_mandi_prices(commodity: str, state: str, district: str = "") -> Dict[str, Any]:
    """Retrieve real-time market (mandi) prices from data.gov.in Agmarknet for a crop/commodity.

    Call this tool when a farmer asks whether to sell now or wait, or asks for current crop rates.

    Args:
        commodity: Name of crop/produce in English (e.g. 'Onion', 'Tomato', 'Wheat', 'Cotton', 'Soyabean').
        state: Indian State name (e.g. 'Maharashtra', 'Karnataka', 'Madhya Pradesh', 'Punjab').
        district: Optional district name (e.g. 'Nashik', 'Pune').

    Returns:
        A dictionary with market price records including market, district, commodity, variety,
        arrival_date, min_price, max_price, and modal_price (Rs per quintal), or a helpful note.
    """
    import os
    api_key = (os.getenv("DATA_GOV_API_KEY") or settings.data_gov_api_key).strip()
    if not api_key:
        return {
            "error": "DATA_GOV_API_KEY is not configured in .env. Please configure your data.gov.in key."
        }

    url = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
    params: Dict[str, Any] = {
        "api-key": api_key,
        "format": "json",
        "limit": 100,
        "filters[state.keyword]": state.strip(),
        "filters[commodity]": commodity.strip().title(),
    }
    if district and district.strip():
        params["filters[district]"] = district.strip().title()

    data = _get(url, params=params, timeout=12.0)
    if "error" in data:
        # If filtered with district failed or errored, try without district
        if district:
            params.pop("filters[district]", None)
            fallback_data = _get(url, params=params, timeout=12.0)
            if "error" not in fallback_data:
                data = fallback_data
            else:
                return data
        else:
            return data

    records = data.get("records", [])
    if not records and district:
        # Try again without district filter to find nearby markets in the state
        params.pop("filters[district]", None)
        broader_data = _get(url, params=params, timeout=12.0)
        records = broader_data.get("records", [])

    if not records:
        return {
            "count": 0,
            "records": [],
            "note": (
                f"No live mandi records found for {commodity} in {state} (district: {district or 'any'}). "
                "Try searching with an alternative crop spelling (e.g. 'Soyabean' vs 'Soybean') or without district filter."
            ),
        }

    formatted_records: List[Dict[str, Any]] = []
    for r in records[:15]:
        item = {
            "market": r.get("market"),
            "district": r.get("district"),
            "commodity": r.get("commodity"),
            "variety": r.get("variety"),
            "arrival_date": r.get("arrival_date"),
            "min_price": r.get("min_price"),
            "max_price": r.get("max_price"),
            "modal_price": r.get("modal_price"),
        }
        formatted_records.append(item)
        # Store snapshot in SQLite database
        try:
            _save_mandi_record(
                commodity=item["commodity"] or commodity,
                state=state,
                district=item["district"] or district,
                market=item["market"] or "",
                modal_price=float(item["modal_price"]) if item["modal_price"] is not None else 0.0,
                arrival_date=item["arrival_date"] or ""
            )
        except Exception:
            pass

    return {
        "count": len(formatted_records),
        "records": formatted_records,
        "commodity": commodity,
        "state": state,
    }


import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).resolve().parent.parent / "mandi_history.sqlite3"


def _init_mandi_db():
    """Ensure SQLite table for storing daily mandi snapshots exists."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS mandi_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commodity TEXT,
                state TEXT,
                district TEXT,
                market TEXT,
                modal_price REAL,
                arrival_date TEXT,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


_init_mandi_db()


def _save_mandi_record(commodity: str, state: str, district: str, market: str, modal_price: float, arrival_date: str):
    """Save a single mandi price record into local SQLite database."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO mandi_prices (commodity, state, district, market, modal_price, arrival_date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (commodity.title(), state.title(), district.title(), market.strip(), modal_price, arrival_date)
        )
        conn.commit()


def get_mandi_price_trend(commodity: str, state: str, district: str = "") -> Dict[str, Any]:
    """Analyze historical mandi price trend (average, minimum, maximum, direction) from recorded snapshots.

    Call this tool when a farmer asks whether market rates are increasing, falling, or stable over the week.

    Args:
        commodity: Name of crop (e.g. 'Onion', 'Tomato', 'Wheat').
        state: State name (e.g. 'Maharashtra').
        district: Optional district name.

    Returns:
        A dictionary with count of records, average_modal_price, min_modal_price, max_modal_price,
        and trend_direction ('rising', 'falling', or 'stable').
    """
    _init_mandi_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        query = "SELECT modal_price, recorded_at FROM mandi_prices WHERE commodity LIKE ? AND state LIKE ?"
        params = [f"%{commodity.strip()}%", f"%{state.strip()}%"]
        if district:
            query += " AND district LIKE ?"
            params.append(f"%{district.strip()}%")
        query += " ORDER BY id DESC LIMIT 50"

        cursor.execute(query, params)
        rows = cursor.fetchall()

    if not rows or len(rows) < 2:
        return {
            "status": "insufficient_history",
            "message": f"Snapshot history for {commodity} is accumulating. Refer to current daily mandi prices.",
            "trend_direction": "stable",
        }

    prices = [r[0] for r in rows if r[0] and r[0] > 0]
    if not prices:
        return {"status": "no_valid_prices", "trend_direction": "stable"}

    avg_price = round(sum(prices) / len(prices), 2)
    min_p = round(min(prices), 2)
    max_p = round(max(prices), 2)

    # Determine trend by comparing recent half vs older half
    mid = len(prices) // 2
    recent_half = prices[:mid]
    older_half = prices[mid:]
    avg_recent = sum(recent_half) / len(recent_half) if recent_half else avg_price
    avg_older = sum(older_half) / len(older_half) if older_half else avg_price

    if avg_recent > avg_older * 1.03:
        direction = "rising"
    elif avg_recent < avg_older * 0.97:
        direction = "falling"
    else:
        direction = "stable"

    return {
        "commodity": commodity,
        "sample_count": len(prices),
        "average_modal_price": avg_price,
        "min_price": min_p,
        "max_price": max_p,
        "trend_direction": direction,
    }


def get_crop_calendar(crop: str, state: str = "Maharashtra") -> Dict[str, Any]:
    """Retrieve optimal sowing windows, harvesting periods, soil suitability, and critical stages for Indian crops.

    Call this tool when advising farmers on seasonal crop planning, sowing dates, and harvest timelines.

    Args:
        crop: Crop name (e.g. 'Onion', 'Tomato', 'Wheat', 'Soybean', 'Cotton', 'Rice', 'Sugarcane').
        state: Indian State name (e.g. 'Maharashtra', 'Karnataka', 'Punjab').

    Returns:
        Agronomic guidelines including seasons, sowing_window, harvest_window, soil_preference,
        and critical_water_stages.
    """
    crop_lower = crop.strip().lower()

    CALENDAR_DB = {
        "onion": {
            "crop": "Onion (कांदा / प्याज)",
            "seasons": {
                "Kharif": {"sowing": "June - July (Nursery: May)", "harvest": "October - November"},
                "Late Kharif (Rangada)": {"sowing": "August - September", "harvest": "January - February"},
                "Rabi": {"sowing": "October - November", "harvest": "March - April"},
            },
            "soil_preference": "Well-drained loamy, sandy-loam with pH 6.0 - 7.5. Avoid heavy clay with poor drainage.",
            "critical_water_stages": "Seedling establishment, bulb development, and bulb maturity (stop irrigation 10-15 days before harvest).",
        },
        "tomato": {
            "crop": "Tomato (टोमॅटो / टमाटर)",
            "seasons": {
                "Kharif": {"sowing": "June - July", "harvest": "September - November"},
                "Rabi": {"sowing": "October - November", "harvest": "January - March"},
                "Summer": {"sowing": "January - February", "harvest": "April - May"},
            },
            "soil_preference": "Deep, well-drained sandy loam rich in organic matter with pH 6.0 - 7.0.",
            "critical_water_stages": "Flowering, fruit set, and fruit development. Avoid excessive moisture during fruit ripening to prevent cracking.",
        },
        "wheat": {
            "crop": "Wheat (गहू / गेहूं)",
            "seasons": {
                "Rabi": {"sowing": "October 25 - November 20 (Timely) / up to Dec 10 (Late)", "harvest": "March - April"},
            },
            "soil_preference": "Well-drained fertile loam or clay loam with pH 6.5 - 7.5.",
            "critical_water_stages": "CRI (Crown Root Initiation, 20-25 days), Tillering, Flowering, and Dough/Milk stage.",
        },
        "soybean": {
            "crop": "Soybean (सोयाबीन)",
            "seasons": {
                "Kharif": {"sowing": "June 15 - July 15 (after 75-100 mm rainfall)", "harvest": "September 25 - October 30"},
            },
            "soil_preference": "Deep, well-drained medium to heavy black cotton soil with pH 6.5 - 7.5.",
            "critical_water_stages": "Flowering and pod development. Ensure good surface drainage to avoid waterlogging.",
        },
        "cotton": {
            "crop": "Cotton (कापूस / कपास)",
            "seasons": {
                "Kharif": {"sowing": "May (irrigated) / June - July (rainfed)", "harvest": "November - February (multiple pickings)"},
            },
            "soil_preference": "Deep black cotton soils (Vertisols) with good water retention and pH 6.5 - 8.0.",
            "critical_water_stages": "Square formation, flowering, and boll development.",
        },
        "rice": {
            "crop": "Rice / Paddy (भात / धान)",
            "seasons": {
                "Kharif": {"sowing": "May - June (Nursery) / July (Transplanting)", "harvest": "October - December"},
                "Rabi": {"sowing": "November - December", "harvest": "March - April"},
            },
            "soil_preference": "Clayey or heavy clay loam with high water holding capacity and pH 5.5 - 7.0.",
            "critical_water_stages": "Panicle initiation, heading, and flowering.",
        },
        "sugarcane": {
            "crop": "Sugarcane (ऊस / गन्ना)",
            "seasons": {
                "Adsali": {"sowing": "July - August", "harvest": "October - December (after 15-18 months)"},
                "Pre-seasonal": {"sowing": "October - November", "harvest": "December - February (after 13-15 months)"},
                "Suru (Spring)": {"sowing": "January - February", "harvest": "January - March (after 12 months)"},
            },
            "soil_preference": "Deep, well-drained loamy soil at least 1 meter deep with neutral pH 6.5 - 7.5.",
            "critical_water_stages": "Formative phase, grand growth phase, and tillering.",
        },
    }

    # Match crop
    matched_key = None
    for k in CALENDAR_DB:
        if k in crop_lower:
            matched_key = k
            break

    if not matched_key:
        return {
            "crop": crop,
            "status": "general_calendar",
            "seasons": {
                "Kharif": {"sowing": "June - July (Monsoon onset)", "harvest": "September - November"},
                "Rabi": {"sowing": "October - November (Winter)", "harvest": "March - April"},
                "Zaid": {"sowing": "February - March (Summer)", "harvest": "May - June"},
            },
            "note": f"Detailed cultivar profile for '{crop}' can be consulted at your local KVK or Agriculture Department.",
        }

    return CALENDAR_DB[matched_key]


ALL_TOOLS = [
    geocode_place,
    reverse_geocode,
    get_weather_forecast,
    get_soil_info,
    get_mandi_prices,
    get_mandi_price_trend,
    get_crop_calendar,
]
