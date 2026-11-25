"""Notification dispatcher and localization engine for KisanSathi.

Handles creation, deduplication, multilingual translation, and safe outbound
Telegram alerts via HTTP.
"""

import logging
import re
from typing import Dict, Optional, Tuple
import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Notification, User

logger = logging.getLogger("kisansathi.notify")

# In-memory translation cache: (text_hash, language) -> translated_text
_TEXT_CACHE: Dict[Tuple[int, str], str] = {}


def send_telegram(chat_id: str, text: str) -> bool:
    """Safely dispatch an outbound message to a linked Telegram chat via HTTP API.

    Never raises unhandled exceptions.
    """
    token = settings.telegram_bot_token.strip()
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            # If markdown entity parsing fails, retry without markdown
            if resp.status_code == 400 and "parse entities" in resp.text.lower():
                payload.pop("parse_mode", None)
                resp2 = client.post(url, json=payload)
                return resp2.status_code == 200
            logger.warning("Telegram send failed (status %d): %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        logger.warning("Telegram HTTP exception for chat %s: %s", chat_id, e)
        return False


def localise_text(text: str, language: str) -> str:
    """Localise text into regional Indian languages using Gemini, with in-memory caching.

    Falls back to original English text without crashing on any failure.
    """
    if not text or not language or language.strip().lower() in ("english", "en", "auto"):
        return text

    clean_lang = language.strip()
    cache_key = (hash(text), clean_lang.lower())
    if cache_key in _TEXT_CACHE:
        return _TEXT_CACHE[cache_key]

    try:
        from google.genai import types
        from app.agent import get_gemini_client

        client = get_gemini_client()
        prompt = (
            f"Translate the following agricultural advisory into {clean_lang} for Indian farmers. "
            f"Maintain natural, respectful farming vocabulary. "
            f"Do NOT use markdown symbols (*, _, #) in the output. "
            f"Output ONLY the translated text without explanations:\n\n{text}"
        )

        model_name = settings.gemini_model or "gemini-3.5-flash"
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )

        translated = (response.text or "").strip()
        # Clean any accidental code fences or markdown bullets
        translated = re.sub(r"^```[a-zA-Z]*\n?", "", translated)
        translated = re.sub(r"\n?```$", "", translated).strip()
        translated = translated.replace("*", "").replace("#", "")

        if translated:
            _TEXT_CACHE[cache_key] = translated
            return translated

    except Exception as e:
        logger.warning("localise_text failed for %s: %s. Returning English.", clean_lang, e)

    return text


def create_notification(
    db: Session,
    user: User,
    kind: str,
    severity: str,
    title: str,
    body: str,
    dedupe_key: Optional[str] = None,
) -> Optional[Notification]:
    """Create and persist a deduplicated notification and dispatch via Telegram if linked."""
    # 1. Deduplication check
    if dedupe_key:
        existing = db.query(Notification).filter(
            Notification.user_id == user.id,
            Notification.dedupe_key == dedupe_key,
        ).first()
        if existing:
            return None

    # 2. Multilingual translation for user's preference
    lang = user.language or "English"
    loc_title = localise_text(title, lang) if lang.lower() != "english" else title
    loc_body = localise_text(body, lang) if lang.lower() != "english" else body

    # 3. Create database record
    notification = Notification(
        user_id=user.id,
        kind=kind,
        severity=severity,
        title=loc_title,
        body=loc_body,
        dedupe_key=dedupe_key,
        read=False,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    # 4. Outbound Telegram alert if chat is linked
    if user.telegram_chat_id:
        telegram_text = f"🌾 *KisanSathi Alert: {loc_title}*\n\n{loc_body}"
        send_telegram(user.telegram_chat_id, telegram_text)

    return notification
