"""Telegram Bot front end for KisanSathi.

Run with:
    python -m bot.telegram_bot
"""

import asyncio
import logging
import sys
from typing import Dict, Tuple

from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.agent import advise
from app.alerts import detect_risks
from app.config import settings

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# In-memory subscription registry: chat_id -> (lat, lon)
SUBSCRIBERS: Dict[int, Tuple[float, float]] = {}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message and location request button."""
    location_button = KeyboardButton(text="📍 Share my location", request_location=True)
    reply_markup = ReplyKeyboardMarkup(
        [[location_button]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )
    welcome_text = (
        "🌾 *Namaste! Welcome to KisanSathi* 🌾\n\n"
        "Your AI Farming Advisor for real-time weather, soil analysis, and mandi prices.\n\n"
        "👉 Tap *'📍 Share my location'* below so I can fetch live data for your farm.\n"
        "Then ask any question in text or send a voice message in Marathi, Hindi, English, or your local language!\n\n"
        "Commands:\n"
        "/subscribe - Receive automatic alerts for heatwaves, frost, and heavy rains."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)


async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Store user's GPS coordinates in user_data."""
    loc = update.message.location
    if loc:
        context.user_data["loc"] = (loc.latitude, loc.longitude)
        await update.message.reply_text(
            f"✅ Farm location saved! ({loc.latitude:.3f}, {loc.longitude:.3f})\n"
            "Now ask your farming question, or use /subscribe for proactive weather alerts."
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text farming questions."""
    user_query = update.message.text
    chat_id = update.effective_chat.id

    # Retrieve saved GPS if present
    lat, lon = context.user_data.get("loc", (None, None))

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        reply = await asyncio.to_thread(
            advise,
            text=user_query,
            lat=lat,
            lon=lon,
            language="auto",
        )
    except Exception as e:
        reply = f"Sorry, could not process your question: {str(e)}"

    await update.message.reply_text(reply)


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice notes from farmers."""
    chat_id = update.effective_chat.id
    voice = update.message.voice
    if not voice:
        return

    lat, lon = context.user_data.get("loc", (None, None))

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        # Download voice note file bytes
        voice_file = await context.bot.get_file(voice.file_id)
        byte_data = await voice_file.download_as_bytearray()
        audio_bytes = bytes(byte_data)

        reply = await asyncio.to_thread(
            advise,
            text=None,
            audio=audio_bytes,
            audio_mime="audio/ogg",
            lat=lat,
            lon=lon,
            language="auto",
        )
    except Exception as e:
        reply = f"Could not process voice note: {str(e)}"

    await update.message.reply_text(reply)


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Subscribe user to automatic 6-hourly weather risk alerts."""
    chat_id = update.effective_chat.id
    loc = context.user_data.get("loc")

    if not loc:
        await update.message.reply_text(
            "⚠️ Please share your farm location first using the '📍 Share my location' button before subscribing."
        )
        return

    SUBSCRIBERS[chat_id] = loc
    await update.message.reply_text(
        f"🔔 Subscribed! You will receive proactive alerts in {settings.alert_language} for heatwaves, frost, and heavy rains."
    )


async def check_alerts_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic job running every 6 hours to check weather risks for all subscribers."""
    logger.info("Running proactive alert check for %d subscribers", len(SUBSCRIBERS))
    for chat_id, (lat, lon) in list(SUBSCRIBERS.items()):
        try:
            risks = await asyncio.to_thread(detect_risks, lat, lon)
            if risks:
                summary_prompt = (
                    f"Create an urgent, direct, 2-line farm weather alert for: {'; '.join(risks)}. "
                    "Tell them practical protection actions."
                )
                alert_text = await asyncio.to_thread(
                    advise,
                    text=summary_prompt,
                    lat=lat,
                    lon=lon,
                    language=settings.alert_language,
                )
                msg = f"🚨 *ALERT: KisanSathi Farm Warning*\n\n{alert_text}"
                await context.bot.send_message(chat_id=chat_id, text=msg)
        except Exception as e:
            logger.error("Failed to deliver alert to %s: %s", chat_id, e)


def create_telegram_app(token: str):
    """Build and configure the Telegram Application instance."""
    app = ApplicationBuilder().token(token).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(MessageHandler(filters.VOICE, voice_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Periodic risk alerts job: runs every 6 hours, initial run after 60s
    if app.job_queue:
        app.job_queue.run_repeating(check_alerts_job, interval=6 * 3600, first=60)
        logger.info("Job queue initialized for 6-hourly proactive alerts.")

    return app


async def start_bot(token: str):
    """Start the Telegram bot asynchronously in background within the existing event loop."""
    app = create_telegram_app(token)
    logger.info("Initializing Telegram Bot for background polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram Bot is running in background polling mode.")
    return app


async def stop_bot(app) -> None:
    """Cleanly shut down the background Telegram bot."""
    if app:
        try:
            logger.info("Stopping Telegram Bot updater...")
            if app.updater and app.updater.running:
                await app.updater.stop()
            logger.info("Stopping Telegram Application...")
            await app.stop()
            await app.shutdown()
            logger.info("Telegram Bot stopped cleanly.")
        except Exception as e:
            logger.error("Error shutting down Telegram bot: %s", e)


def main() -> None:
    """Start the Telegram bot in standalone mode."""
    token = settings.telegram_bot_token.strip()
    if not token:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set in your .env file. "
            "Please add TELEGRAM_BOT_TOKEN to enable the Telegram bot."
        )
        sys.exit(1)

    app = create_telegram_app(token)
    logger.info("KisanSathi Telegram Bot is starting polling in standalone mode...")
    app.run_polling()


if __name__ == "__main__":
    main()
