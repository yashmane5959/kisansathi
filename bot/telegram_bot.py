"""Telegram Bot front end for KisanSathi.

Run with:
    python -m bot.telegram_bot
"""

import asyncio
import logging
import sys
from typing import Dict, Optional, Tuple

from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.error import BadRequest, Conflict, TelegramError
from telegram.ext import (
    Application,
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


async def safe_reply(
    msg,
    text: str,
    reply_markup=None,
    parse_mode: Optional[str] = "Markdown",
) -> None:
    """Send a reply to the user safely, gracefully degrading to plain text if Markdown fails."""
    if not msg:
        return
    try:
        await msg.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except BadRequest as e:
        logger.warning("Markdown formatting failed (%s). Retrying as plain text.", e)
        try:
            await msg.reply_text(text, parse_mode=None, reply_markup=reply_markup)
        except Exception as inner_e:
            logger.error("Failed to deliver plain text message: %s", inner_e)
    except Exception as e:
        logger.error("Failed to send message: %s", e)


def get_user_location(context: ContextTypes.DEFAULT_TYPE) -> Tuple[Optional[float], Optional[float]]:
    """Safely extract stored (latitude, longitude) from context.user_data."""
    if context.user_data is None:
        return None, None
    loc = context.user_data.get("loc")
    if isinstance(loc, (tuple, list)) and len(loc) == 2:
        try:
            return float(loc[0]), float(loc[1])
        except (ValueError, TypeError):
            return None, None
    return None, None


def get_user_language(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Retrieve saved language preference or default alert language."""
    if context.user_data is not None:
        lang = context.user_data.get("language")
        if lang:
            return str(lang)
    return settings.alert_language or "Hindi"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message and location request button, listing all commands."""
    msg = update.effective_message or update.message
    if not msg:
        return

    try:
        location_button = KeyboardButton(text="📍 Share my location", request_location=True)
        reply_markup = ReplyKeyboardMarkup(
            [[location_button]],
            resize_keyboard=True,
            one_time_keyboard=False,
        )
        welcome_text = (
            "🌾 *Namaste! Welcome to KisanSathi* 🌾\n\n"
            "Your AI Agricultural Advisor for real-time weather, soil analysis, and mandi prices.\n\n"
            "👉 Tap *'📍 Share my location'* below so I can fetch live data for your farm.\n"
            "You can type questions or send voice notes in Hindi, Marathi, English, or your local language!\n\n"
            "*Available Commands:*\n"
            "• /crop [crop] — Crop suggestion, suitability & calendar\n"
            "• /weather — 7-day farm weather forecast & risk warnings\n"
            "• /mandi [crop] — Live APMC market prices & sell vs. wait advice\n"
            "• /fertilizer [crop] — Soil-based fertilizer & nutrient guidance\n"
            "• /subscribe — 6-hourly proactive extreme weather warnings\n"
            "• /help — Detailed instructions and command guide"
        )
        await safe_reply(msg, welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.exception("Error in /start command: %s", e)
        await safe_reply(
            msg,
            "🌾 Namaste! Welcome to KisanSathi. Please share your location or ask any farming question.",
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send detailed help guide with instructions on text, voice, and all commands."""
    msg = update.effective_message or update.message
    if not msg:
        return

    try:
        help_text = (
            "🌾 *KisanSathi Help & Usage Guide* 🌾\n\n"
            "*How to use:*\n"
            "1. 📍 *Share Location:* Tap '📍 Share my location' so the bot can fetch hyper-local data for your village/district.\n"
            "2. 💬 *Ask Questions:* Simply type any farming question (e.g. 'Can I spray pesticide tomorrow?' or 'Should I harvest onions?').\n"
            "3. 🎙️ *Voice Notes:* Record and send a voice audio note in Marathi, Hindi, English, or your regional language.\n\n"
            "*Commands Reference:*\n"
            "• `/crop [crop]` — Check seasonal suitability, soil fitness, and sowing/harvesting timing (e.g. `/crop onion` or `/crop wheat`)\n"
            "• `/weather` — Get a 7-day agricultural forecast with heatwave, rain, or frost warnings\n"
            "• `/mandi [crop]` — Check current APMC wholesale prices and receive sell or wait advice (e.g. `/mandi tomato`)\n"
            "• `/fertilizer [crop]` — Soil-specific fertilizer application stages and nutrient advice (e.g. `/fertilizer cotton`)\n"
            "• `/subscribe` — Enroll in automatic 6-hourly extreme weather alerts\n"
            "• `/help` — Show this message"
        )
        await safe_reply(msg, help_text, parse_mode="Markdown")
    except Exception as e:
        logger.exception("Error in /help command: %s", e)
        await safe_reply(msg, "🌾 KisanSathi: Please ask any farming question or use /start to begin.")


async def require_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Tuple[Optional[float], Optional[float]]:
    """Check if the user has shared location; if not, prompt them with the location button."""
    try:
        lat, lon = get_user_location(context)
        if lat is None or lon is None:
            location_button = KeyboardButton(text="📍 Share my location", request_location=True)
            reply_markup = ReplyKeyboardMarkup(
                [[location_button]],
                resize_keyboard=True,
                one_time_keyboard=False,
            )
            msg = update.effective_message or update.message
            if msg:
                await safe_reply(
                    msg,
                    "⚠️ Please tap *'📍 Share my location'* below first so I can fetch live weather, soil, and mandi data for your farm.",
                    reply_markup=reply_markup,
                    parse_mode="Markdown",
                )
            return None, None
        return lat, lon
    except Exception as e:
        logger.exception("Error checking location: %s", e)
        return None, None


async def crop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /crop command with optional crop name argument."""
    msg = update.effective_message or update.message
    if not msg:
        return

    try:
        lat, lon = await require_location(update, context)
        if lat is None or lon is None:
            return

        crop_name = " ".join(context.args).strip() if context.args else ""
        if not crop_name:
            await safe_reply(
                msg,
                "🌾 Which crop would you like advice on?\n"
                "Please send the command with a crop name, for example:\n"
                "• `/crop onion`\n"
                "• `/crop wheat`\n"
                "• `/crop tomato`",
                parse_mode="Markdown",
            )
            return

        chat_id = update.effective_chat.id if update.effective_chat else msg.chat_id
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        lang = get_user_language(context)
        prompt = (
            f"Provide comprehensive crop advisory for {crop_name}. "
            "Check local soil properties (clay, sand, pH) and upcoming 7-day weather. "
            "Advise on seasonal suitability, sowing or harvest timing, and key care tips."
        )

        reply = await asyncio.to_thread(
            advise,
            text=prompt,
            lat=lat,
            lon=lon,
            language=lang,
        )
        await safe_reply(msg, reply, parse_mode=None)
    except Exception as e:
        logger.exception("Error in /crop command: %s", e)
        await safe_reply(
            msg,
            "🌾 KisanSathi: Could not process crop advisory at this moment. Please check your farm location and try again.",
        )


async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /weather command for 7-day agricultural weather forecast."""
    msg = update.effective_message or update.message
    if not msg:
        return

    try:
        lat, lon = await require_location(update, context)
        if lat is None or lon is None:
            return

        chat_id = update.effective_chat.id if update.effective_chat else msg.chat_id
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        lang = get_user_language(context)
        extra = " ".join(context.args).strip() if context.args else ""
        prompt = (
            "Provide a 7-day agricultural weather forecast summary. "
            "Highlight maximum/minimum temperatures, rain probability, and any heatwave or frost risks. "
            "Give actionable farm protection advice (e.g. irrigation timing or pesticide spraying window)."
        )
        if extra:
            prompt += f" Note farmer focus: {extra}."

        reply = await asyncio.to_thread(
            advise,
            text=prompt,
            lat=lat,
            lon=lon,
            language=lang,
        )
        await safe_reply(msg, reply, parse_mode=None)
    except Exception as e:
        logger.exception("Error in /weather command: %s", e)
        await safe_reply(
            msg,
            "🌾 KisanSathi: Could not fetch weather forecast at this moment. Please try again shortly.",
        )


async def mandi_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /mandi command with optional commodity argument."""
    msg = update.effective_message or update.message
    if not msg:
        return

    try:
        lat, lon = await require_location(update, context)
        if lat is None or lon is None:
            return

        commodity = " ".join(context.args).strip() if context.args else ""
        if not commodity:
            await safe_reply(
                msg,
                "📊 Which crop market prices are you looking for?\n"
                "Please send the command with a crop name, for example:\n"
                "• `/mandi onion`\n"
                "• `/mandi tomato`\n"
                "• `/mandi soybean`",
                parse_mode="Markdown",
            )
            return

        chat_id = update.effective_chat.id if update.effective_chat else msg.chat_id
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        lang = get_user_language(context)
        prompt = (
            f"Fetch current mandi market wholesale prices for {commodity} in my state and district. "
            "Analyze whether the farmer should sell now or wait based on prices and upcoming weather."
        )

        reply = await asyncio.to_thread(
            advise,
            text=prompt,
            lat=lat,
            lon=lon,
            language=lang,
        )
        await safe_reply(msg, reply, parse_mode=None)
    except Exception as e:
        logger.exception("Error in /mandi command: %s", e)
        await safe_reply(
            msg,
            "🌾 KisanSathi: Could not fetch mandi market prices right now. Please try again in a few moments.",
        )


async def fertilizer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /fertilizer command for soil-based nutrient guidance."""
    msg = update.effective_message or update.message
    if not msg:
        return

    try:
        lat, lon = await require_location(update, context)
        if lat is None or lon is None:
            return

        crop_name = " ".join(context.args).strip() if context.args else ""
        if not crop_name:
            await safe_reply(
                msg,
                "🌱 Which crop do you need fertilizer guidance for?\n"
                "Please send the command with a crop name, for example:\n"
                "• `/fertilizer wheat`\n"
                "• `/fertilizer cotton`\n"
                "• `/fertilizer sugarcane`",
                parse_mode="Markdown",
            )
            return

        chat_id = update.effective_chat.id if update.effective_chat else msg.chat_id
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        lang = get_user_language(context)
        prompt = (
            f"Provide fertilizer and nutrient schedule guidance for {crop_name} based on local soil properties (clay, pH, SOC). "
            "Suggest basal and top-dressing stages, mention organic alternatives, and remind to confirm doses with local KVK."
        )

        reply = await asyncio.to_thread(
            advise,
            text=prompt,
            lat=lat,
            lon=lon,
            language=lang,
        )
        await safe_reply(msg, reply, parse_mode=None)
    except Exception as e:
        logger.exception("Error in /fertilizer command: %s", e)
        await safe_reply(
            msg,
            "🌾 KisanSathi: Could not fetch fertilizer guidance at this moment. Please try again shortly.",
        )


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unrecognized slash commands."""
    msg = update.effective_message or update.message
    if msg:
        try:
            await safe_reply(
                msg,
                "❓ Unrecognized command. Tap /help to see all available farming commands.",
            )
        except Exception as e:
            logger.error("Error in unknown_command handler: %s", e)


async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Store user's GPS coordinates in user_data."""
    msg = update.effective_message or update.message
    if not msg or not msg.location:
        return

    try:
        loc = msg.location
        if context.user_data is not None:
            context.user_data["loc"] = (float(loc.latitude), float(loc.longitude))

        await safe_reply(
            msg,
            f"✅ Farm location saved! ({loc.latitude:.3f}, {loc.longitude:.3f})\n"
            "Now ask your farming question, or use /subscribe for proactive weather alerts.",
        )
    except Exception as e:
        logger.exception("Error saving location: %s", e)
        await safe_reply(msg, "⚠️ Could not save your location. Please try tapping 'Share my location' again.")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text farming questions."""
    msg = update.effective_message or update.message
    if not msg or not msg.text:
        return

    user_query = msg.text
    chat_id = update.effective_chat.id if update.effective_chat else msg.chat_id

    # Retrieve saved GPS safely
    lat, lon = get_user_location(context)

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception as e:
        logger.warning("Could not send typing action: %s", e)

    try:
        reply = await asyncio.to_thread(
            advise,
            text=user_query,
            lat=lat,
            lon=lon,
            language="auto",
        )
    except Exception as e:
        logger.exception("Error processing question '%s': %s", user_query[:50], e)
        reply = "🌾 किसान साथी: आपका प्रश्न प्रोसेस करने में अस्थायी समस्या आई है। कृपया कुछ क्षणों बाद पुनः प्रयास करें। (Unable to process question, please retry in a moment.)"

    await safe_reply(msg, reply, parse_mode=None)


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice notes from farmers."""
    msg = update.effective_message or update.message
    if not msg or not msg.voice:
        return

    chat_id = update.effective_chat.id if update.effective_chat else msg.chat_id
    lat, lon = get_user_location(context)

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception as e:
        logger.warning("Could not send typing action for voice note: %s", e)

    try:
        voice_file = await context.bot.get_file(msg.voice.file_id)
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
        logger.exception("Error processing voice note: %s", e)
        reply = "🌾 Could not process your voice note. Please speak clearly or send your question as text."

    await safe_reply(msg, reply, parse_mode=None)


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Subscribe user to automatic 6-hourly weather risk alerts."""
    msg = update.effective_message or update.message
    if not msg:
        return

    try:
        chat_id = update.effective_chat.id if update.effective_chat else msg.chat_id
        lat, lon = get_user_location(context)

        if lat is None or lon is None:
            await safe_reply(
                msg,
                "⚠️ Please share your farm location first using the '📍 Share my location' button before subscribing.",
            )
            return

        SUBSCRIBERS[chat_id] = (lat, lon)
        await safe_reply(
            msg,
            f"🔔 Subscribed! You will receive proactive alerts in {settings.alert_language} for heatwaves, frost, and heavy rains.",
        )
    except Exception as e:
        logger.exception("Error in /subscribe command: %s", e)
        await safe_reply(msg, "⚠️ Could not complete subscription. Please try again.")


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


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle uncaught errors across the Telegram Application."""
    err = context.error
    if isinstance(err, Conflict):
        logger.error(
            "FATAL CONFLICT: Another instance of the Telegram bot is already running with this token (HTTP 409 Conflict). "
            "Ensure only ONE process is running!"
        )
        return

    logger.error("Telegram error occurred while processing update: %s", err, exc_info=err)

    if isinstance(update, Update) and update.effective_message:
        try:
            await safe_reply(
                update.effective_message,
                "🌾 KisanSathi: A temporary issue occurred while processing your request. Please try again in a few moments.",
                parse_mode=None,
            )
        except Exception as e:
            logger.error("Failed to send error message to user: %s", e)


def create_telegram_app(token: str) -> Application:
    """Build and configure the Telegram Application instance with all agricultural command handlers."""
    app = ApplicationBuilder().token(token).build()

    # Register global error handler
    app.add_error_handler(global_error_handler)

    # Command Handlers (registered before generic text handler)
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("crop", crop_command))
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("mandi", mandi_command))
    app.add_handler(CommandHandler("fertilizer", fertilizer_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))

    # Location & Voice Handlers
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(MessageHandler(filters.VOICE, voice_handler))

    # Generic text handler (ensuring it never swallows commands)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Fallback for unrecognized slash commands
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Periodic risk alerts job: runs every 6 hours, initial run after 60s
    if app.job_queue:
        app.job_queue.run_repeating(check_alerts_job, interval=6 * 3600, first=60)
        logger.info("Job queue initialized for 6-hourly proactive alerts.")

    return app


def run_bot_in_background(token: str):
    """Run Telegram bot polling in a dedicated background daemon thread."""
    import threading

    def _worker():
        try:
            logger.info("Starting Telegram Bot polling in background daemon thread...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            app = create_telegram_app(token)
            # stop_signals=None prevents signal handler crashes in worker threads
            app.run_polling(stop_signals=None, close_loop=False)
        except Exception as e:
            logger.error("Telegram bot background thread failed: %s", e)

    thread = threading.Thread(target=_worker, daemon=True, name="TelegramBotWorker")
    thread.start()
    return thread


async def start_bot(token: str) -> Application:
    """Start the Telegram bot asynchronously in background within the existing event loop."""
    app = create_telegram_app(token)
    logger.info("Initializing Telegram Bot for background polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram Bot is running in background polling mode.")
    return app


async def stop_bot(app: Optional[Application]) -> None:
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
