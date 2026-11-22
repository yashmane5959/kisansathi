# KisanSathi Upgrade Spec (for Antigravity)

Save this file as `docs/UPGRADE_SPEC.md` inside the project. Then tell Antigravity:

> Read docs/UPGRADE_SPEC.md fully. Execute it phase by phase. After each phase run the Verify steps and fix every failure before starting the next phase. Do not skip phases. Do not break existing features.

---

## 0. Goal

KisanSathi today is a question-and-answer advisor. Upgrade it into an **AI farm agent that knows each farmer and watches the farm every day**:

1. **Login and farm profile** (stored in a database)
2. **Crop planner:** the farmer picks a crop and sowing date and gets a dated **roadmap** (stages, watering, fertiliser, pest watch, harvest)
3. **Smart daily watering decision** based on evapotranspiration and rain (not a fixed schedule)
4. **Live climate watch** that notifies the farmer when the forecast turns dangerous or changes
5. **Stage-based fertiliser guidance** using soil data
6. **Notifications** in the app and on Telegram, including a spoken-style **morning briefing** in the farmer's language

Extra features that make it stand out (build them, they are small):

- **Farm Risk Score (0-100)** shown as a gauge on the dashboard
- **Water Saved counter** (litres saved versus a fixed watering schedule), the impact number for the pitch
- **"Forecast changed" alert** when the new forecast differs a lot from the last one
- **Demo Mode** button that simulates a heatwave, heavy rain or frost, so judges can see alerts instantly

Hackathon track: Climate, Resource Infrastructure & Global Supply Resilience.

---

## 1. Golden rules (these prevent most errors)

1. **Do not break what already works:** `/api/advise`, `/api/advise-audio`, `/api/alerts`, `/api/diagnose-crop`, `/api/health`, the Telegram bot, and the existing chat UI. Commit to git before you start (`git add . ; git commit -m "before upgrade"`).
2. **Code collects data, the LLM only phrases it.** Weather, water balance, roadmap dates, fertiliser stage, and risk score are computed by deterministic Python. Gemini is used only to (a) answer free questions with tools (existing), (b) translate or phrase text into the farmer's language. **Never let the LLM invent numbers.**
3. **Every Gemini call must be wrapped in try/except with an English fallback.** Gemini has rate limits. Never call Gemini inside loops over many users without a per-user daily cache.
4. **Every external HTTP call has a timeout and returns a dict with `error` instead of raising.** Cache weather per location for 30 minutes (in memory dict keyed by rounded lat/lon).
5. **Windows safety:** the developer uses Windows PowerShell. Never `print()` emojis or non-ASCII (it raises `UnicodeEncodeError` on cp1252 consoles). Use plain ASCII in logs. Use `pathlib` for paths. Add `tzdata` to requirements (the `zoneinfo` timezone `Asia/Kolkata` fails on Windows without it).
6. **Use SQLAlchemy 2.0 style** (`DeclarativeBase`, `Mapped`, `mapped_column`, `Session`). Create tables on startup with `Base.metadata.create_all(engine)`.
7. **Database URL:** read `DATABASE_URL` from `.env`. Default to `sqlite:///./kisansathi.db`. If the URL starts with `postgres://` or `postgresql://`, rewrite it to `postgresql+psycopg2://`. For SQLite pass `connect_args={"check_same_thread": False}`.
8. **Passwords:** use only the standard library: `hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)` with a random 16-byte salt from `secrets.token_bytes`, compared with `hmac.compare_digest`. Do **not** use passlib (it breaks with new bcrypt versions).
9. **Sessions:** random token via `secrets.token_urlsafe(32)` stored in a `sessions` table. The browser keeps it in `localStorage` and sends `Authorization: Bearer <token>`. Session lifetime 30 days.
10. **APScheduler:** install `apscheduler>=3.10,<4` (version 4 has a different API). Use `AsyncIOScheduler` started inside the FastAPI `lifespan`.
11. **Gemini function calling and JSON mode cannot be combined.** For any call that needs JSON output (translation of the roadmap), do **not** pass `tools`. Use `response_mime_type="application/json"`, parse with `json.loads`, strip code fences first, validate the length and keys, and fall back to English if parsing fails.
12. **Tool functions for Gemini** must have type hints and docstrings, return JSON-serialisable dicts, and must not use `from __future__ import annotations`.
13. **Nominatim** needs a User-Agent header and at most 1 request per second. Cache reverse geocoding results per rounded lat/lon.
14. **Dates:** store dates as `date`, timestamps as UTC `datetime`. Convert to `Asia/Kolkata` only for display and for scheduling.
15. **Never commit `.env` or the `.db` file.** Add `*.db` and `*.sqlite3` to `.gitignore`.
16. Keep all farmer-facing text **short, simple, speakable** (no markdown symbols).
17. Advice is guidance only. Every fertiliser or pesticide message ends with: confirm doses with a soil test or the local agriculture office (KVK).

---

## 2. New dependencies

Append to `requirements.txt`, then run `python -m pip install -r requirements.txt` inside the existing virtual environment:

```
sqlalchemy>=2.0
psycopg2-binary>=2.9
apscheduler>=3.10,<4
tzdata
```

Add to `.env.example` and `.env`:

```
DATABASE_URL=sqlite:///./kisansathi.db
APP_TIMEZONE=Asia/Kolkata
MORNING_HOUR=6
MORNING_MINUTE=30
RUN_SCHEDULER=true
RUN_BOT_IN_APP=false
```

---

## 3. New folder structure (add, do not delete existing files)

```
app/
  db.py              engine, SessionLocal, Base, get_db dependency
  models.py          SQLAlchemy models
  auth.py            hashing, register/login helpers, current_user dependency
  crop_data.py       crop templates (stages, Kc, fertiliser, sensitivities)
  weather.py         cached forecast fetch incl. ET0 and past days
  planner.py         roadmap builder, irrigation engine, fertiliser, risk score
  climate_watch.py   threshold alerts and "forecast changed" detection
  notify.py          create notification rows, send Telegram, localise text
  scheduler.py       APScheduler jobs
  routes_farm.py     /api/auth, /api/profile, /api/crops, /api/today, /api/notifications, /api/demo
web/
  login.html         register and login
  dashboard.html     main app after login
  app.js             shared JS (auth, fetch helper, speech)
  styles.css         shared styles
scripts/
  smoke_test.py      end-to-end test against the running server
docs/
  UPGRADE_SPEC.md    this file
```

`app/main.py` must include the new router (`app.include_router(router)`), create tables on startup, start the scheduler in `lifespan`, and serve `login.html` and `dashboard.html`. The route `/` redirects to `/login` (a plain HTML page that itself forwards to `/dashboard` when a token exists in `localStorage`). Keep the old chat page reachable at `/chat`.
