"""Weather risk detection and proactive farmer alerts."""

from typing import List
from app.tools import get_weather_forecast


def detect_risks(lat: float, lon: float) -> List[str]:
    """Inspect next 3 days of weather forecast for agricultural risk events.

    Flags:
    - Heavy rain: precipitation >= 50 mm
    - Heatwave: maximum temperature >= 40 C
    - Cold night: minimum temperature <= 6 C

    Args:
        lat: Latitude of location.
        lon: Longitude of location.

    Returns:
        List of human-readable risk description strings with dates, or an empty list if no risks or error.
    """
    try:
        forecast = get_weather_forecast(lat, lon)
        if isinstance(forecast, dict) and "error" in forecast:
            return []

        if not isinstance(forecast, list):
            return []

        risks: List[str] = []
        # Examine next 3 days
        for day in forecast[:3]:
            date_str = day.get("date", "Upcoming day")
            rain_mm = day.get("rain_mm") or 0.0
            temp_max = day.get("temp_max_c")
            temp_min = day.get("temp_min_c")

            if rain_mm >= 50.0:
                risks.append(f"Heavy rain warning on {date_str} ({rain_mm:.1f} mm expected). Ensure adequate field drainage and postpone pesticide spraying.")

            if temp_max is not None and temp_max >= 40.0:
                risks.append(f"Severe heatwave alert on {date_str} (High of {temp_max:.1f} °C). Irrigate standing crops in the evening or early morning to prevent moisture stress.")

            if temp_min is not None and temp_min <= 6.0:
                risks.append(f"Cold night and frost risk on {date_str} (Low of {temp_min:.1f} °C). Provide light irrigation or smoke mulching to protect sensitive seedlings.")

        return risks
    except Exception:
        return []
