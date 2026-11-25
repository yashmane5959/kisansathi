"""Agricultural roadmap planner and localization engine for KisanSathi.

Builds dated, weather-aware growth roadmaps for farmer crops and localises
stages into regional Indian languages using Gemini.
"""

import copy
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from app.crop_data import get_crop_data

logger = logging.getLogger("kisansathi.planner")


def build_roadmap(crop_row: Any, forecast_days: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Build a dated growth roadmap for a crop with weather warnings and current stage highlight.

    Args:
        crop_row: A Crop model instance or object with .crop and .sowing_date attributes.
        forecast_days: Optional 14-day weather forecast list from app.weather.get_forecast.

    Returns:
        A list of stage dictionaries including dated boundaries, Kc, notes, and flags.
    """
    crop_name = getattr(crop_row, "crop", str(crop_row))
    crop_info = get_crop_data(crop_name)
    if not crop_info:
        # Fallback generic crop template
        crop_info = {
            "canonical_name": crop_name,
            "duration_days": 120,
            "sensitivity": {"heat_c": 38.0, "cold_c": 8.0, "heavy_rain_mm": 50.0},
            "stages": [
                {
                    "name": "Establishment",
                    "start_day": 0,
                    "end_day": 30,
                    "kc": 0.5,
                    "water_note": "Initial establishment watering.",
                    "fert_note": "Basal fertiliser dose.",
                    "pest_note": "Monitor young seedlings.",
                },
                {
                    "name": "Vegetative & Flowering",
                    "start_day": 31,
                    "end_day": 90,
                    "kc": 1.0,
                    "water_note": "Regular irrigation schedule.",
                    "fert_note": "Top-dress nitrogen.",
                    "pest_note": "Inspect for foliar pests.",
                },
                {
                    "name": "Maturity",
                    "start_day": 91,
                    "end_day": 120,
                    "kc": 0.7,
                    "water_note": "Taper off watering before harvest.",
                    "fert_note": "No fertiliser.",
                    "pest_note": "Harvest when mature.",
                },
            ],
        }

    sowing_date = getattr(crop_row, "sowing_date", None)
    if not sowing_date:
        sowing_date = date.today()
    elif isinstance(sowing_date, str):
        sowing_date = datetime.strptime(sowing_date, "%Y-%m-%d").date()

    today = date.today()
    days_since_sowing = (today - sowing_date).days
    sensitivity = crop_info.get("sensitivity", {})
    heat_thresh = sensitivity.get("heat_c", 40.0)
    cold_thresh = sensitivity.get("cold_c", 6.0)
    rain_thresh = sensitivity.get("heavy_rain_mm", 50.0)

    stages_result: List[Dict[str, Any]] = []
    has_current = False

    for stg in crop_info["stages"]:
        start_day = stg["start_day"]
        end_day = stg["end_day"]
        start_dt = sowing_date + timedelta(days=start_day)
        end_dt = sowing_date + timedelta(days=end_day)

        is_current = (start_day <= days_since_sowing <= end_day)
        is_completed = (days_since_sowing > end_day)

        if is_current:
            has_current = True

        # Check forecast for extreme weather during this stage's window
        weather_note = ""
        if forecast_days:
            for f_day in forecast_days:
                f_date_str = f_day.get("date")
                if not f_date_str:
                    continue
                try:
                    f_dt = datetime.strptime(f_date_str, "%Y-%m-%d").date()
                except Exception:
                    continue

                if start_dt <= f_dt <= end_dt:
                    rain = f_day.get("rain_mm", 0.0)
                    tmax = f_day.get("tmax", 30.0)
                    tmin = f_day.get("tmin", 20.0)

                    if rain >= rain_thresh:
                        weather_note = f"Heavy rain ({rain} mm) alert around {f_date_str}. Delay spraying and clear drainage."
                        break
                    elif tmax >= heat_thresh:
                        weather_note = f"High temperature ({tmax}°C) alert around {f_date_str}. Maintain soil moisture."
                        break
                    elif tmin <= cold_thresh:
                        weather_note = f"Cold night ({tmin}°C) alert around {f_date_str}. Protect sensitive foliage."
                        break

        stages_result.append({
            "name": stg["name"],
            "start_day": start_day,
            "end_day": end_day,
            "start_date": start_dt.isoformat(),
            "end_date": end_dt.isoformat(),
            "kc": stg["kc"],
            "water_note": stg["water_note"],
            "fert_note": stg["fert_note"],
            "pest_note": stg["pest_note"],
            "weather_note": weather_note,
            "is_current": is_current,
            "is_completed": is_completed,
        })

    # Add final Harvest window stage
    duration = crop_info["duration_days"]
    harvest_start_day = max(0, duration - 10)
    harvest_start_dt = sowing_date + timedelta(days=harvest_start_day)
    harvest_end_dt = sowing_date + timedelta(days=duration)
    is_harvest_current = (days_since_sowing >= harvest_start_day and not has_current)
    is_harvest_completed = (days_since_sowing > duration)

    if is_harvest_current:
        has_current = True

    stages_result.append({
        "name": "Harvest window",
        "start_day": harvest_start_day,
        "end_day": duration,
        "start_date": harvest_start_dt.isoformat(),
        "end_date": harvest_end_dt.isoformat(),
        "kc": crop_info["stages"][-1]["kc"] if crop_info["stages"] else 0.5,
        "water_note": "Final field preparation for harvesting. Ensure soil is sufficiently firm and produce is dry.",
        "fert_note": "No fertiliser application; harvest crop at optimal maturity.",
        "pest_note": "Ensure clean storage, sorting, and grading to prevent post-harvest loss.",
        "weather_note": "",
        "is_current": is_harvest_current,
        "is_completed": is_harvest_completed,
    })

    # If sowing date is in the future, mark the first stage as current
    if not has_current and days_since_sowing < 0 and stages_result:
        stages_result[0]["is_current"] = True
    elif not has_current and days_since_sowing > duration and stages_result:
        stages_result[-1]["is_current"] = True

    return stages_result


MARATHI_STAGE_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "Establishment": {
        "name": "रोप स्थापना अवस्था (Establishment)",
        "water_note": "रोपांची मुळे पकडण्यासाठी हलके व नियमित पाणी द्या; शेतात पाणी साचू देऊ नका.",
        "fert_note": "लागवडीवेळी चांगले कुजलेले शेणखत, सिंगल सुपर फॉस्फेट आणि पोटॅशची बेसल मात्रा द्या.",
        "pest_note": "रोपवाटिकेत रोपांची मर आणि सुरुवातीच्या थ्रिप्स (फुलकिडे) प्रादुर्भावावर बारीक लक्ष ठेवा.",
    },
    "Leaf growth": {
        "name": "शाकीय पात वाढ अवस्था (Leaf growth)",
        "water_note": "दर ५ ते ७ दिवसांनी नियमित पाणी द्या; जोमदार वाढीच्या काळात पाण्याचा ताण पडू देऊ नका.",
        "fert_note": "नत्राचा पहिला हप्ता द्या; कांद्याची प्रत आणि तिखटपणा सुधारण्यासाठी गंधक (सल्फर) वापरा.",
        "pest_note": "पानांच्या बेचक्यात थ्रिप्स (फुलकिडे) आणि जांभळा करपा रोगाच्या डागांची पाहणी करा.",
    },
    "Bulb formation": {
        "name": "कांदा फुगवण अवस्था (Bulb formation)",
        "water_note": "कांदा पोसण्याचा हा महत्त्वाचा टप्पा; कांदा फाटू नये म्हणून जमिनीत नियमित ओलावा ठेवा.",
        "fert_note": "कांदा घट्ट व चमकदार होण्यासाठी पोटॅश द्या; जाड मान व सड टाळण्यासाठी नत्र देणे बंद करा.",
        "pest_note": "ढगाळ व दमट हवामानात जांभळा करपा रोगाचा धोका वाढतो; खालच्या पानांची पाहणी करा.",
    },
    "Maturity": {
        "name": "परिपक्वता अवस्था (Maturity)",
        "water_note": "काढणीच्या १० ते १५ दिवस आधी पाणी पूर्णपणे बंद करा, जेणेकरून कांद्याची मान सुकेल व साठवण टिकेल.",
        "fert_note": "कोणतेही खत देऊ नका; पाती नैसर्गिकरीत्या पिवळी पडून जमिनीवर आडवी होऊ द्या.",
        "pest_note": "मान सड व बुरशी तपासा; कांदा उपटण्यापूर्वी जमिनीचा वरचा थर पूर्णपणे कोरडा असावा.",
    },
    "Harvest window": {
        "name": "काढणी काळ (Harvest window)",
        "water_note": "काढणीसाठी शेत तयार करा; जमीन कोरडी ठेवा व साठवणुकीची जागा स्वच्छ ठेवा.",
        "fert_note": "खत देण्याची गरज नाही; पक्व झालेला कांदा काळजीपूर्वक काढा.",
        "pest_note": "काढणीनंतर कांदा सावलीत वाळवा आणि खराब कांदे वेगळे करून प्रतवारी करा.",
    },
    "Vegetative": {
        "name": "शाकीय वाढ अवस्था (Vegetative)",
        "water_note": "ठिबक किंवा पाटाने नियमित पाणी द्या; बुरशीचा प्रसार रोखण्यासाठी पानांवर पाणी उडवणे टाळा.",
        "fert_note": "जोमदार फुटव्यांसाठी नत्र, कॅल्शियम आणि बोरॉनची मात्रा द्या.",
        "pest_note": "पानांवरील नागअळीच्या रेषा आणि करपा रोगाच्या डागांवर बारीक लक्ष ठेवा.",
    },
    "Flowering and fruiting": {
        "name": "फूल व फळ धारणा अवस्था (Flowering & fruiting)",
        "water_note": "पाण्याचा अत्यंत संवेदनशील टप्पा; पाण्याचा ताण पडल्यास फूलगळ व फळे तडकण्याची शक्यता असते.",
        "fert_note": "फळांचा आकार व चमक वाढवण्यासाठी पोटॅश द्या; अतिरिक्त नत्र देणे टाळा.",
        "pest_note": "ढगाळ हवामानात फळ पोखरणारी अळी आणि बुरशीजन्य करप्याचा प्रादुर्भाव तपासा.",
    },
    "Harvest": {
        "name": "तोडणी व काढणी (Harvest)",
        "water_note": "तोडणीच्या दरम्यान हलके पाणी द्या; कमी पाणी दिल्यास फळांची गोडी व टिकवण क्षमता वाढते.",
        "fert_note": "पुढील तोडणी सुरू असल्यास हलकी पोटॅश मात्रा कायम ठेवा.",
        "pest_note": "किडकी व खराब झालेली फळे गोळा करून नष्ट करा; ओल्या फळांची तोडणी करू नका.",
    },
    "Tillering": {
        "name": "फुटवे फुटण्याची अवस्था (Tillering)",
        "water_note": "फुटवे जोमदार येण्यासाठी जमिनीतील ओलावा कायम ठेवा.",
        "fert_note": "जमिनीत पुरेसा ओलावा असताना युरियाचा पहिला हप्ता द्या.",
        "pest_note": "पानांवरील तांबेरा व मावा किडीच्या प्रादुर्भावाची पाहणी करा.",
    },
    "Flowering": {
        "name": "फुलोरा अवस्था (Flowering)",
        "water_note": "फुलोऱ्याच्या अवस्थेत पाण्याचा ताण पडू देऊ नका; योग्य पाणी व्यवस्थापन करा.",
        "fert_note": "कमी प्रमाणात नत्र किंवा पोटॅशियम नायट्रेटची फवारणी करा.",
        "pest_note": "धुक्याच्या आणि दमट वातावरणात भुरी रोगाचा प्रादुर्भाव तपासा.",
    },
    "Grain filling and ripening": {
        "name": "दाणे भरणे व पक्वता (Grain filling)",
        "water_note": "दाणे भरण्याच्या वेळी हलके पाणी द्या; पीक लोळू नये म्हणून वादळी व वाऱ्याच्या दिवशी पाणी देणे टाळा.",
        "fert_note": "खत देण्याची गरज नाही; दाणे भरण्याची नैसर्गिक प्रक्रिया सुरू आहे.",
        "pest_note": "लोंब्यांवरील किडी व पक्ष्यांच्या त्रासापासून पिकाचे रक्षण करा.",
    },
}


def localise_roadmap(stages: List[Dict[str, Any]], language: str) -> List[Dict[str, Any]]:
    """Localise roadmap stage names, water, fertiliser, pest, and weather notes using Gemini.

    Falls back to English stages without crashing if language is English, API is unavailable,
    or translation fails.
    """
    if not language or language.strip().lower() in ("english", "en", "auto"):
        return stages

    clean_lang = language.strip()

    try:
        from google.genai import types
        from app.agent import get_gemini_client
        from app.config import settings

        client = get_gemini_client()

        # Build concise payload for translation to minimise token usage and latency
        trans_input = []
        for s in stages:
            trans_input.append({
                "name": s["name"],
                "water_note": s["water_note"],
                "fert_note": s["fert_note"],
                "pest_note": s["pest_note"],
                "weather_note": s.get("weather_note", ""),
            })

        prompt = (
            f"You are an agricultural expert translator. Translate the following crop growth stages and farming advice "
            f"into {clean_lang} for Indian farmers. Keep agricultural terms accurate and natural in {clean_lang}.\n"
            f"Respond with a JSON array having the exact same number of elements with keys: "
            f"\"name\", \"water_note\", \"fert_note\", \"pest_note\", \"weather_note\".\n\n"
            f"Input JSON:\n{json.dumps(trans_input, ensure_ascii=False)}"
        )

        candidate_models = []
        if settings.gemini_model:
            candidate_models.append(settings.gemini_model)
        for m in ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-latest"):
            if m not in candidate_models:
                candidate_models.append(m)

        for model_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )

                resp_text = (response.text or "").strip()
                # Strip markdown fences if present
                if resp_text.startswith("```"):
                    resp_text = re.sub(r"^```[a-zA-Z]*\n?", "", resp_text)
                    resp_text = re.sub(r"\n?```$", "", resp_text).strip()

                translated_list = json.loads(resp_text)
                if isinstance(translated_list, list) and len(translated_list) == len(stages):
                    localised_stages: List[Dict[str, Any]] = []
                    for orig, trans in zip(stages, translated_list):
                        new_stg = copy.deepcopy(orig)
                        if isinstance(trans, dict):
                            new_stg["name"] = trans.get("name") or orig["name"]
                            new_stg["water_note"] = trans.get("water_note") or orig["water_note"]
                            new_stg["fert_note"] = trans.get("fert_note") or orig["fert_note"]
                            new_stg["pest_note"] = trans.get("pest_note") or orig["pest_note"]
                            if "weather_note" in trans and trans["weather_note"]:
                                new_stg["weather_note"] = trans["weather_note"]
                        localised_stages.append(new_stg)
                    return localised_stages
            except Exception as model_err:
                logger.info("Roadmap model %s failed for %s: %s. Trying next...", model_name, clean_lang, model_err)

    except Exception as e:
        logger.warning("Roadmap localisation into %s failed: %s. Checking glossary fallback.", clean_lang, e)

    # If Gemini translation was unavailable and language is Marathi, check built-in glossary
    if clean_lang.lower() == "marathi":
        localised_stages: List[Dict[str, Any]] = []
        for orig in stages:
            new_stg = copy.deepcopy(orig)
            trans = MARATHI_STAGE_TRANSLATIONS.get(orig["name"])
            if trans:
                new_stg["name"] = trans.get("name") or orig["name"]
                new_stg["water_note"] = trans.get("water_note") or orig["water_note"]
                new_stg["fert_note"] = trans.get("fert_note") or orig["fert_note"]
                new_stg["pest_note"] = trans.get("pest_note") or orig["pest_note"]
            localised_stages.append(new_stg)
        return localised_stages

    return stages


# ============================================================================
# Phase 3: Irrigation Engine, Fertiliser Guidance, and Risk Scoring
# ============================================================================

def irrigation_decision(
    crop_row: Any,
    user: Any,
    days: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Calculate soil moisture deficit, threshold, and irrigation advice for today.

    Formulas:
      - Kc = current stage crop coefficient (or last stage if outside duration)
      - Start tracking from max(last_watered or sowing_date, today - 7 days)
      - Effective rain = 0.8 * rain_mm (if rain_mm >= 5 mm else 0)
      - Deficit += (et0 * kc - effective_rain), clamped >= 0
      - Threshold: sandy = 20 mm, loamy = 30 mm, clayey = 40 mm, unknown = 30 mm
      - Water today if deficit >= threshold and no rain >= 8 mm forecast today or tomorrow
      - Gross mm = net mm / efficiency (drip 0.9, flood 0.6)
      - Litres = gross mm * 4047 * area_acres
    """
    today = date.today()
    sowing_date = getattr(crop_row, "sowing_date", today)
    if isinstance(sowing_date, str):
        sowing_date = datetime.strptime(sowing_date, "%Y-%m-%d").date()

    last_watered = getattr(crop_row, "last_watered", None)
    if isinstance(last_watered, str):
        last_watered = datetime.strptime(last_watered, "%Y-%m-%d").date()

    # Determine start date for deficit accumulation
    seven_days_ago = today - timedelta(days=7)
    water_anchor = last_watered if last_watered else sowing_date
    start_date = max(water_anchor, seven_days_ago)

    # Determine Kc of current stage
    crop_name = getattr(crop_row, "crop", "Onion")
    crop_info = get_crop_data(crop_name)
    days_since_sowing = (today - sowing_date).days

    kc = 0.8
    current_stage_name = "Growth"
    if crop_info and crop_info.get("stages"):
        stages = crop_info["stages"]
        for stg in stages:
            if stg["start_day"] <= days_since_sowing <= stg["end_day"]:
                kc = stg["kc"]
                current_stage_name = stg["name"]
                break
        else:
            kc = stages[-1]["kc"]
            current_stage_name = stages[-1]["name"]

    # Soil depletion threshold
    texture_str = (getattr(user, "soil_texture", "") or "").lower().strip()
    if "sand" in texture_str:
        threshold = 20.0
        threshold_desc = "sandy soil threshold of 20 mm"
    elif "clay" in texture_str:
        threshold = 40.0
        threshold_desc = "clayey soil threshold of 40 mm"
    elif "loam" in texture_str:
        threshold = 30.0
        threshold_desc = "loamy soil threshold of 30 mm"
    else:
        threshold = 30.0
        threshold_desc = "default soil threshold of 30 mm (soil type not set)"

    # Default fallback weather if days is missing or empty
    if not days:
        days = []
        for offset in range(-7, 8):
            d = today + timedelta(days=offset)
            days.append({
                "date": d.isoformat(),
                "tmax": 32.0,
                "tmin": 20.0,
                "rain_mm": 0.0,
                "rain_prob": 10,
                "et0": 4.5,
                "is_past": d < today,
            })

    # Accumulate daily soil moisture deficit from start_date through today
    deficit = 0.0
    total_et0_past = 0.0
    rain_past_days = 0.0
    tracked_days_count = 0

    for d in days:
        d_str = d.get("date")
        if not d_str:
            continue
        try:
            d_date = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        if start_date <= d_date <= today:
            tracked_days_count += 1
            et0 = float(d.get("et0", 4.5))
            total_et0_past += et0
            rain = float(d.get("rain_mm", 0.0))
            rain_past_days += rain
            eff_rain = 0.8 * rain if rain >= 5.0 else 0.0
            daily_loss = (et0 * kc) - eff_rain
            deficit += daily_loss
            if deficit < 0.0:
                deficit = 0.0

    deficit = round(deficit, 1)

    # Inspect upcoming forecast: rain today or tomorrow
    tomorrow = today + timedelta(days=1)
    rain_today = 0.0
    rain_tomorrow = 0.0
    next_rain = "No significant rain forecast in next 7 days"
    found_next_rain = False

    for d in days:
        d_str = d.get("date")
        if not d_str:
            continue
        try:
            d_date = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        rain_val = float(d.get("rain_mm", 0.0))
        if d_date == today:
            rain_today = rain_val
        elif d_date == tomorrow:
            rain_tomorrow = rain_val

        if d_date >= today and rain_val >= 5.0 and not found_next_rain:
            next_rain = f"{d_str} ({rain_val} mm, {d.get('rain_prob', 0)}% prob)"
            found_next_rain = True

    rain_48h = max(rain_today, rain_tomorrow)
    rain_incoming = rain_48h >= 8.0

    irrigation_type = getattr(crop_row, "irrigation_type", "drip").lower()
    area_acres = float(getattr(crop_row, "area_acres", 1.0) or 1.0)

    # 1. Rainfed crop: Never recommend irrigation
    if irrigation_type == "rainfed":
        if deficit >= threshold:
            reason = (
                f"Rainfed crop: cumulative moisture deficit is {deficit:.1f} mm, exceeding the {threshold_desc} "
                f"(ET0 sum {total_et0_past:.1f} mm, past rain {rain_past_days:.1f} mm). "
                f"Do not irrigate; apply straw mulching or interculture to conserve subsoil moisture."
            )
        else:
            reason = (
                f"Rainfed crop: cumulative moisture deficit is {deficit:.1f} mm, safely below the {threshold_desc}. "
                f"Soil moisture is sufficient."
            )
        return {
            "water_today": False,
            "mm": 0.0,
            "net_mm": 0.0,
            "litres": 0,
            "reason": reason,
            "next_rain": next_rain,
            "deficit": deficit,
            "threshold": threshold,
            "kc": kc,
            "stage": current_stage_name,
        }

    # 2. Irrigated crops (drip or flood)
    water_today = (deficit >= threshold) and not rain_incoming
    net_mm = deficit if water_today else 0.0
    efficiency = 0.9 if irrigation_type == "drip" else 0.6
    gross_mm = round(net_mm / efficiency, 1) if water_today else 0.0
    litres = int(round(gross_mm * 4047.0 * area_acres))

    avg_et0 = round(total_et0_past / max(1, tracked_days_count), 1)

    if water_today:
        reason = (
            f"Water today: soil moisture deficit is {deficit:.1f} mm, which exceeds the {threshold_desc} "
            f"(avg ET0 {avg_et0} mm/day, Kc {kc}, past rain {rain_past_days:.1f} mm). "
            f"Apply {gross_mm:.1f} mm ({litres:,} litres on {area_acres} acres using {irrigation_type} system)."
        )
    elif rain_incoming:
        reason = (
            f"Skip irrigation: significant rain of {rain_48h:.1f} mm is forecast within 48h. "
            f"Current deficit is {deficit:.1f} mm against {threshold_desc}. Next rain: {next_rain}."
        )
    else:
        reason = (
            f"No watering needed today: current deficit is {deficit:.1f} mm, remaining below the {threshold_desc} "
            f"(Kc {kc}, avg ET0 {avg_et0} mm/day). Next expected rain: {next_rain}."
        )

    return {
        "water_today": water_today,
        "mm": gross_mm,
        "net_mm": net_mm,
        "litres": litres,
        "reason": reason,
        "next_rain": next_rain,
        "deficit": deficit,
        "threshold": threshold,
        "kc": kc,
        "stage": current_stage_name,
    }


def fertiliser_guidance(crop_row: Any, user: Any) -> str:
    """Generate agronomic fertiliser guidance based on crop growth stage and soil parameters.

    Never mentions specific kg/acre doses; always ends with mandatory KVK / soil test reminder.
    """
    today = date.today()
    sowing_date = getattr(crop_row, "sowing_date", today)
    if isinstance(sowing_date, str):
        sowing_date = datetime.strptime(sowing_date, "%Y-%m-%d").date()

    days_since_sowing = (today - sowing_date).days
    crop_name = getattr(crop_row, "crop", "Onion")
    crop_info = get_crop_data(crop_name)

    fert_note = "Maintain balanced organic and mineral nutrition suited to vegetative vigor."
    stage_name = "Active Growth"
    if crop_info and crop_info.get("stages"):
        stages = crop_info["stages"]
        for stg in stages:
            if stg["start_day"] <= days_since_sowing <= stg["end_day"]:
                fert_note = stg["fert_note"]
                stage_name = stg["name"]
                break
        else:
            fert_note = stages[-1]["fert_note"]
            stage_name = stages[-1]["name"]

    soil_flags: List[str] = []
    ph = getattr(user, "soil_ph", None)
    if ph is not None:
        try:
            ph_val = float(ph)
            if ph_val < 5.5:
                soil_flags.append(
                    f"Soil pH is acidic ({ph_val:.1f}). Apply agricultural lime / dolomite based on soil test to improve nutrient availability."
                )
            elif ph_val > 8.5:
                soil_flags.append(
                    f"Soil pH is alkaline ({ph_val:.1f}). Incorporate gypsum, pressmud, and farmyard manure (FYM) to improve permeability and lower sodicity."
                )
        except Exception:
            pass

    oc = getattr(user, "soil_oc", None)
    if oc is not None:
        try:
            oc_val = float(oc)
            if oc_val < 10.0:
                soil_flags.append(
                    f"Soil organic carbon is low ({oc_val:.1f} g/kg). Add well-decomposed compost, cow dung manure, or green manuring to boost microbial activity."
                )
        except Exception:
            pass

    mandatory_reminder = (
        "Note: Always verify fertilizer dosages with a certified soil health card or consult your local "
        "Krishi Vigyan Kendra (KVK) / block agriculture officer before field application. Specific kg-per-acre "
        "rates must be adjusted to your soil test results to prevent nutrient burning."
    )

    parts = [f"Stage ({stage_name}): {fert_note}"]
    if soil_flags:
        parts.append("Soil Health Alerts: " + " ".join(soil_flags))
    parts.append(mandatory_reminder)

    return "\n\n".join(parts)


def calculate_risk_score(
    crop_row: Any,
    user: Any,
    days: Optional[List[Dict[str, Any]]] = None,
    deficit_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Calculate the 0-100 Farm Risk Score for a crop.

    Deductions:
      - -25 for each extreme weather day in next 3 days (heat, cold, heavy rain)
      - -10 for rain probability > 70% during harvest stage
      - -15 if rainfed and deficit >= threshold
      - Clamped between 0 and 100
    Labels:
      - 80+: Good
      - 50-79: Watch
      - <50: High risk
    """
    score = 100
    reasons: List[str] = []

    today = date.today()
    sowing_date = getattr(crop_row, "sowing_date", today)
    if isinstance(sowing_date, str):
        sowing_date = datetime.strptime(sowing_date, "%Y-%m-%d").date()

    days_since_sowing = (today - sowing_date).days
    crop_name = getattr(crop_row, "crop", "Onion")
    crop_info = get_crop_data(crop_name)

    sensitivity = crop_info.get("sensitivity", {}) if crop_info else {}
    heat_thresh = sensitivity.get("heat_c", 40.0)
    cold_thresh = sensitivity.get("cold_c", 6.0)
    rain_thresh = sensitivity.get("heavy_rain_mm", 50.0)

    # Evaluate next 3 days of forecast
    if days:
        future_days = [d for d in days if d.get("date") and d["date"] >= today.isoformat()][:3]
        for d in future_days:
            tmax = float(d.get("tmax", 30.0))
            tmin = float(d.get("tmin", 20.0))
            rain = float(d.get("rain_mm", 0.0))
            d_date = d.get("date", "")

            day_threats = []
            if tmax >= heat_thresh:
                day_threats.append(f"extreme heat ({tmax}°C)")
            if tmin <= cold_thresh:
                day_threats.append(f"cold night ({tmin}°C)")
            if rain >= rain_thresh:
                day_threats.append(f"heavy rainfall ({rain} mm)")

            if day_threats:
                score -= 25
                reasons.append(f"Alert on {d_date}: {', '.join(day_threats)} exceeding crop tolerance.")

        # Harvest stage rain risk
        if crop_info:
            duration = crop_info.get("duration_days", 120)
            if days_since_sowing >= duration - 15:
                rain_harvest = [d for d in future_days if int(d.get("rain_prob", 0)) > 70]
                if rain_harvest:
                    score -= 10
                    reasons.append(f"Rain probability >70% on {rain_harvest[0]['date']} during sensitive harvest window.")

    # Rainfed moisture stress
    irrigation_type = getattr(crop_row, "irrigation_type", "drip").lower()
    if irrigation_type == "rainfed" and deficit_info:
        deficit_val = deficit_info.get("deficit", 0.0)
        thresh_val = deficit_info.get("threshold", 30.0)
        if deficit_val >= thresh_val:
            score -= 15
            reasons.append(f"Rainfed moisture stress: root-zone deficit ({deficit_val:.1f} mm) exceeds threshold ({thresh_val:.0f} mm).")

    score = max(0, min(100, score))

    if score >= 80:
        level = "Good"
        if not reasons:
            reasons.append("Favorable weather conditions, balanced temperatures, and stable soil moisture.")
    elif score >= 50:
        level = "Watch"
    else:
        level = "High risk"

    return {
        "score": score,
        "level": level,
        "reasons": reasons,
    }


def calculate_overall_risk(crop_risks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate individual crop risk evaluations into a farm-level risk score."""
    if not crop_risks:
        return {
            "score": 100,
            "level": "Good",
            "reasons": ["No active crops registered."],
        }

    min_score = min(cr.get("score", 100) for cr in crop_risks)
    all_reasons = []
    for cr in crop_risks:
        for r in cr.get("reasons", []):
            if r not in all_reasons and not r.startswith("Favorable"):
                all_reasons.append(r)

    if not all_reasons:
        all_reasons = ["Favorable weather conditions and stable moisture across all farm plots."]

    if min_score >= 80:
        level = "Good"
    elif min_score >= 50:
        level = "Watch"
    else:
        level = "High risk"

    return {
        "score": min_score,
        "level": level,
        "reasons": all_reasons,
    }

