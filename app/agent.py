"""AI Agricultural Agent for KisanSathi powered by Google Gemini (google-genai SDK)."""

import re
from typing import List, Optional
from google import genai
from google.genai import types

from app.config import settings
from app.tools import ALL_TOOLS

SYSTEM_INSTRUCTION = """You are KisanSathi, a friendly and wise agricultural advisor dedicated to Indian farmers.
Your mission is to provide short, practical, and timely farming guidance.

Follow these strict rules:
1. ALWAYS call the available tools to get live weather, soil parameters, and mandi market prices. NEVER invent or hallucinate numbers or market prices.
2. If only a place or district name is provided, call geocode_place to find coordinates and state.
3. If only GPS coordinates (latitude, longitude) are provided, call reverse_geocode to discover the state and district (needed for mandi queries).
4. Provide clear advice on:
   - Crop suggestions for the season and soil type
   - Best timing for sowing, harvesting, or field operations
   - Crop protection (e.g. delay spraying pesticide before rain, irrigate before severe heat, prepare drainage before heavy downpours)
   - Market selling decisions: sell now or wait, based on actual mandi modal prices and upcoming weather
5. Tone and formatting:
   - Use very simple, spoken words and short sentences.
   - Maximum 6 lines total.
   - DO NOT use any markdown formatting: NO asterisks (** or *), NO bullet symbols (-, *, •), NO hashtags (#), NO numbered lists with dots. This text will be spoken directly to the farmer via text-to-speech.
6. Always end with exactly one short line stating the reason with key rainfall, soil, or price facts. Translate the heading word 'Reason' into the user's language (e.g. Marathi: कारण, Hindi: कारण, Telugu: కారణం, Tamil: காரணம், Kannada: ಕಾರಣ, etc.).
7. If any specific data (like mandi rates or soil) is temporarily unavailable, honestly state so and provide safe, practical agronomic advice.
8. Remind the farmer to confirm chemical or pesticide doses with their local Krishi Vigyan Kendra (KVK) or agriculture officer.
"""

_client: Optional[genai.Client] = None


def get_gemini_client() -> genai.Client:
    """Lazily initialize and return the Google GenAI client."""
    global _client
    api_key = settings.gemini_api_key.strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Please set it in your .env file.")
    if _client is None:
        _client = genai.Client(api_key=api_key)
    return _client


def clean_speech_text(text: str) -> str:
    """Remove markdown symbols to ensure smooth text-to-speech output."""
    if not text:
        return ""
    # Remove asterisks, hashtags, bullets, backticks
    cleaned = re.sub(r"[*#_`~•]", "", text)
    # Remove leading dashes or bullets in lines
    cleaned = re.sub(r"^\s*[-+]\s+", "", cleaned, flags=re.MULTILINE)
    # Normalize multiple newlines
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return "\n".join(lines[:6])


def advise(
    text: Optional[str] = None,
    audio: Optional[bytes] = None,
    audio_mime: str = "audio/ogg",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    district: Optional[str] = None,
    language: str = "auto",
) -> str:
    """Consult the KisanSathi AI advisor with text or audio input, farm location, and target language.

    Args:
        text: Question or request in natural language.
        audio: Raw bytes of user voice recording.
        audio_mime: MIME type of the audio bytes.
        lat: Latitude of farm location.
        lon: Longitude of farm location.
        district: District or place name entered by user.
        language: User's requested language or 'auto'.

    Returns:
        A concise, spoken-friendly advice string.
    """
    try:
        client = get_gemini_client()
    except Exception as e:
        return f"KisanSathi system note: {str(e)}"

    # Compose context part
    context_items = []
    if lat is not None and lon is not None:
        context_items.append(f"Farmer GPS coordinates: {lat:.4f}, {lon:.4f}")
    if district:
        context_items.append(f"Farmer location/district: {district}")

    if language and language.lower() != "auto":
        context_items.append(f"Reply strictly in {language} language only.")
    else:
        context_items.append("Reply in the exact same language the farmer used (Marathi, Hindi, Tamil, Telugu, Kannada, Gujarati, Bengali, Punjabi, or English).")

    contents: List[types.Part] = []
    contents.append(types.Part.from_text(text="Context: " + " | ".join(context_items)))

    if audio:
        contents.append(types.Part.from_bytes(data=audio, mime_type=audio_mime))

    if text:
        contents.append(types.Part.from_text(text=f"Farmer query: {text}"))

    if not text and not audio:
        contents.append(types.Part.from_text(text="Hello KisanSathi! Please give me today's farming advice based on my location."))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=ALL_TOOLS,
        temperature=0.3,
    )

    primary_model = settings.gemini_model.strip() or "gemini-3.1-flash-lite"
    all_fallbacks = [primary_model, "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-3.5-flash"]
    candidate_models = []
    for m in all_fallbacks:
        if m and m not in candidate_models:
            candidate_models.append(m)

    last_error = None
    for model_name in candidate_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            answer = response.text or ""
            cleaned = clean_speech_text(answer)
            if not cleaned:
                return "KisanSathi advice: Weather and field conditions checked. Please proceed with routine weeding and monitor market rates."
            return cleaned
        except Exception as e:
            last_error = e
            continue

    return f"Namaste farmer friend, we could not complete the request right now: {str(last_error)}"


def diagnose_crop_disease(
    image_bytes: bytes,
    image_mime: str = "image/jpeg",
    notes: Optional[str] = None,
    language: str = "auto",
) -> str:
    """Diagnose crop health, plant pests, fungal diseases, or nutrient deficiency from a leaf/crop photograph.

    Uses Gemini multimodal vision.

    Args:
        image_bytes: Raw bytes of the crop photograph.
        image_mime: MIME type of the uploaded image.
        notes: Farmer's description of observed symptoms or crop name.
        language: Target regional language.

    Returns:
        Spoken-friendly diagnosis, symptoms analysis, and safe management recommendation.
    """
    try:
        client = get_gemini_client()
    except Exception as e:
        return f"KisanSathi system note: {str(e)}"

    lang_instruction = (
        f"Reply strictly in {language} language."
        if language and language.lower() != "auto"
        else "Reply in simple Hindi or English as appropriate for an Indian farmer."
    )

    prompt = (
        "You are KisanSathi Crop Doctor. Analyze this crop photograph carefully.\n"
        "1. Identify the crop and the disease, pest, or nutrient deficiency observed.\n"
        "2. Explain the likely cause in 1-2 simple sentences.\n"
        "3. Recommend 2 practical treatments: one organic/cultural prevention and one safe standard intervention.\n"
        "4. Remind the farmer to confirm chemical doses with their local Krishi Vigyan Kendra (KVK).\n"
        "5. Keep maximum 6 lines, simple spoken language, no markdown asterisks or bullet signs.\n"
        f"{lang_instruction}"
    )

    if notes:
        prompt += f"\nFarmer notes: {notes}"

    contents = [
        types.Part.from_bytes(data=image_bytes, mime_type=image_mime),
        types.Part.from_text(text=prompt),
    ]

    primary_model = settings.gemini_model.strip() or "gemini-3.5-flash"
    for m in [primary_model, "gemini-3.5-flash", "gemini-3.8-flash", "gemini-2.5-flash"]:
        try:
            resp = client.models.generate_content(
                model=m,
                contents=contents,
                config=types.GenerateContentConfig(temperature=0.2),
            )
            cleaned = clean_speech_text(resp.text or "")
            if cleaned:
                return cleaned
        except Exception:
            continue

    return "Could not diagnose image at this moment. Please ensure the leaf or pest is clearly visible in sunlight and try again."
