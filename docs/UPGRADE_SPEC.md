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

---

## 4. Data model (`app/models.py`)

**User**: `id`, `username` (unique, lowercase), `password_hash` (hex), `salt` (hex), `name`, `phone` (nullable), `language` (default `Marathi`, store the language name such as Marathi, Hindi, Tamil, Telugu, Kannada, Gujarati, Bengali, Punjabi, English), `village`, `district`, `state`, `lat`, `lon` (floats, nullable), `soil_texture` (nullable), `soil_ph`, `soil_oc` (nullable floats), `telegram_chat_id` (nullable string), `link_code` (nullable string), `demo_scenario` (nullable string), `created_at`.

**Session**: `token` (primary key), `user_id`, `created_at`.

**Crop** (one farmer can have several): `id`, `user_id`, `crop` (one of the supported crops), `area_acres` (float), `sowing_date` (date), `irrigation_type` (`rainfed`, `drip`, `flood`), `last_watered` (date, nullable), `status` (`active` or `harvested`), `roadmap_json` (text), `roadmap_lang` (text), `created_at`.

**Notification**: `id`, `user_id`, `kind` (`briefing`, `watering`, `climate`, `forecast_change`, `fertiliser`, `info`), `severity` (`info`, `warning`, `danger`), `title`, `body`, `created_at`, `read` (bool).

**WateringLog**: `id`, `crop_id`, `date`, `action` (`watered` or `skipped`), `mm_applied`, `mm_saved`.

**ForecastSnapshot**: `id`, `user_id`, `taken_at`, `summary_json` (3-day totals: rain_mm, tmax, tmin).

**Reminders de-duplication:** add a `dedupe_key` (string, indexed, nullable) to Notification, for example `climate:2026-11-23:heatwave`, and never create two notifications with the same `user_id` and `dedupe_key`.

Also keep the existing mandi history table if it exists.

---

## 5. Business logic specs

### 5.1 `crop_data.py`

Supported crops: Onion, Tomato, Wheat, Soybean, Cotton, Rice, Sugarcane. For each crop store:

- `duration_days`
- `stages`: list of `{name, start_day, end_day, kc, water_note, fert_note, pest_note}` where days are counted after sowing or transplanting
- `sensitivity`: `{heat_c, cold_c, heavy_rain_mm}` (defaults: heat 40, cold 6, rain 50)

Use these approximate defaults (these are general guidance, mark them as such in the UI):

| Crop | Duration | Stages (day range, Kc) | Sensitivity |
|---|---|---|---|
| Onion | 120 | Establishment 0-20 (0.5), Leaf growth 21-60 (0.8), Bulb formation 61-100 (1.05), Maturity 101-120 (0.75) | heat 40, cold 6, rain 50 |
| Tomato | 120 | Establishment 0-20 (0.6), Vegetative 21-50 (0.9), Flowering and fruiting 51-90 (1.15), Harvest 91-120 (0.8) | heat 35, cold 8, rain 40 |
| Wheat | 125 | Establishment 0-20 (0.4), Tillering 21-60 (0.8), Flowering 61-100 (1.15), Grain filling and ripening 101-125 (0.4) | heat 35, cold 2, rain 40 |
| Soybean | 100 | Establishment 0-15 (0.4), Vegetative 16-45 (0.8), Flowering and pod fill 46-80 (1.1), Maturity 81-100 (0.5) | heat 38, cold 10, rain 60 |
| Cotton | 170 | Establishment 0-30 (0.4), Vegetative 31-80 (0.8), Flowering and boll set 81-130 (1.15), Boll opening 131-170 (0.7) | heat 40, cold 10, rain 60 |
| Rice | 125 | Establishment 0-20 (1.05), Tillering 21-60 (1.1), Panicle and flowering 61-90 (1.2), Ripening 91-125 (0.9) | heat 38, cold 12, rain 150 |
| Sugarcane | 365 | Germination 0-35 (0.4), Tillering 36-120 (0.8), Grand growth 121-270 (1.25), Maturity 271-365 (0.75) | heat 42, cold 8, rain 80 |

Write short `water_note`, `fert_note`, `pest_note` strings per stage in plain English. Use these themes:

- **Fertiliser:** basal dose of organic manure with phosphorus and potash at sowing or planting; nitrogen split into two or three top-dressings at tillering, vegetative or flowering stages; sulphur and micronutrients where relevant; no nitrogen late near maturity; potash during bulb or fruit formation.
- **Water:** stop irrigation about 10-15 days before onion harvest; drain rice fields about 10 days before harvest; critical irrigation stages for wheat are crown root initiation (about day 21), tillering, flowering and grain filling.
- **Pest watch:** general weather-linked advice only (for example "humid weather raises fungal disease risk, inspect leaves"). Do not give pesticide brand names or exact doses.

### 5.2 `weather.py`

`get_forecast(lat, lon)` calls Open-Meteo forecast with daily `temperature_2m_max, temperature_2m_min, precipitation_sum, precipitation_probability_max, et0_fao_evapotranspiration`, `timezone=auto`, `past_days=7`, `forecast_days=7`. Return a list of day dicts with `date` (ISO), `tmax`, `tmin`, `rain_mm`, `rain_prob`, `et0`, plus a flag `is_past`. Cache for 30 minutes. If the demo scenario is set for the user, `apply_demo(days, scenario)` overrides the next 3 days (heatwave: tmax 44; heavyrain: rain_mm 90; frost: tmin 2). Never apply demo values to the cache itself, only to a copy.

### 5.3 `planner.py`

**Roadmap:** `build_roadmap(crop_row)` returns a list of stages with real dates (`sowing_date + start_day`), the stage notes, and a `weather_note` filled when a heavy-rain or heat day from the forecast falls inside the stage window. Include a final "Harvest window" item at `duration_days`. Mark the current stage using today's date. Store the English version in `roadmap_json`.

**Localise:** `localise_roadmap(stages, language)` makes one Gemini call (no tools, JSON mode) to translate `title`, `water`, `fertiliser`, `pest`, `weather_note` of each stage. Cache the result in `roadmap_json` with `roadmap_lang`. On any failure return the English stages.

**Irrigation engine:** `irrigation_decision(crop_row, user, days)`:
1. `kc` = Kc of the current stage (if the crop is outside its duration, use the last stage).
2. Start from `max(last_watered or sowing_date, today - 7 days)`. For each day from there through today: `deficit += et0 * kc - effective_rain`, where `effective_rain = 0.8 * rain_mm` if `rain_mm >= 5` else 0. Clamp `deficit >= 0`.
3. Threshold by soil texture (mm of allowed depletion): sandy 20, loamy 30, clay 40, unknown 30.
4. If irrigation type is `rainfed`: do not recommend watering. Recommend mulching or protective steps when deficit is above threshold.
5. Otherwise: `water_today = deficit >= threshold` and no rain of 8 mm or more is forecast for today or tomorrow. `net_mm = deficit`. `gross_mm = net_mm / efficiency` (drip 0.9, flood 0.6). `litres = gross_mm * 4047 * area_acres` (1 mm over 1 acre is about 4047 litres).
6. Return `{water_today, mm, litres, reason, next_rain}`. The reason must mention the numbers used, for example "ET0 5 mm, no rain in 3 days".

**Water saved:** compare to a baseline of watering every 3 days at 25 mm net. When the farmer taps "skipped due to rain" or the engine says no watering needed, record `mm_saved` in `WateringLog`. The dashboard shows total litres saved (`mm_saved * 4047 * area_acres`).

**Fertiliser guidance:** `fertiliser_guidance(crop_row, user)` returns the current stage `fert_note` plus soil flags from the profile: pH below 5.5 means acidic soil (advise soil test and liming guidance from the local office); pH above 8.5 means alkaline (gypsum, organic matter); organic carbon below 10 g/kg means low (add compost or farmyard manure). Always append the confirm-with-soil-test line. Never output kg per acre numbers.

**Farm Risk Score:** start at 100. Subtract 25 for each danger day in the next 3 days (heat, cold or heavy rain by crop sensitivity), 10 for any day with rain probability above 70 percent during harvest-stage, 15 if irrigation is needed now but unavailable (rainfed with deficit above threshold), 10 if the forecast changed strongly. Clamp 0-100. Return the score plus a list of reasons. Label: 80+ Good, 50-79 Watch, below 50 High risk.

### 5.4 `climate_watch.py`

`check_user(user, session)` for each active crop:
1. Fetch the forecast (with demo override if set).
2. For the next 3 days, flag heatwave (`tmax >= sensitivity.heat_c`), cold (`tmin <= cold_c`), heavy rain (`rain_mm >= heavy_rain_mm`). Create a notification of kind `climate`, severity `danger`, with `dedupe_key = f"climate:{date}:{type}:{crop_id}"`.
3. Take a 3-day summary and compare with the last `ForecastSnapshot`. If total rain changed by 20 mm or more, or max temperature changed by 4 C or more, create a `forecast_change` notification (dedupe per day). Save the new snapshot.
4. Each alert body includes the specific action (for example "Heavy rain tomorrow: delay spraying and fertiliser, clear drains.").

### 5.5 `notify.py`

- `create_notification(session, user, kind, severity, title, body, dedupe_key=None)` stores a row (skips if the dedupe key exists), then if `telegram_chat_id` is set and `TELEGRAM_BOT_TOKEN` exists, sends the message through `https://api.telegram.org/bot<TOKEN>/sendMessage` using `httpx.post(..., timeout=15)` inside try/except.
- `localise_text(text, language)`: one Gemini call, no tools, plain text output. Cache by `(hash(text), language)` in memory. On failure return the English text. Skip the call when language is English.
- Build alerts in English first, then localise the title and body for the user's language.

### 5.6 Morning briefing (`scheduler.py`)

Every day at `MORNING_HOUR:MORNING_MINUTE` in `APP_TIMEZONE`, for each user with an active crop:
1. Compute stage, irrigation decision, risk score, fertiliser note, and the top alert if any.
2. Build an English briefing of at most 6 short lines: greeting with name, today's weather in one line, stage and day count, watering yes/no with litres, one fertiliser or pest tip, one risk line.
3. Localise with `localise_text`, save as a `briefing` notification (dedupe key `briefing:<date>`), and send on Telegram.
4. Also run `climate_watch.check_user` every 3 hours for all users with a location.

Schedule: use `CronTrigger(hour=..., minute=..., timezone=ZoneInfo(...))` and `IntervalTrigger(hours=3)`. Give each job `max_instances=1`, `coalesce=True`, `misfire_grace_time=3600`. Wrap each user's processing in try/except so one failure never stops the loop. Only start the scheduler if `RUN_SCHEDULER=true`.

---

## 6. API spec (`app/routes_farm.py`, prefix `/api`)

All routes except register and login require the Bearer token (dependency `current_user`, return 401 if missing or expired).

| Method and path | Purpose |
|---|---|
| `POST /auth/register` | body: username, password (min 6 chars), name, language, village, district, state, lat?, lon?. If lat/lon missing, geocode village/district with the existing `geocode_place`. Returns token and profile. Username taken returns 409. |
| `POST /auth/login` | username, password. Returns token and profile. Wrong credentials returns 401 with a generic message. |
| `POST /auth/logout` | deletes the session |
| `GET /profile` and `PUT /profile` | read and update profile (language, location, soil info, telegram) |
| `POST /profile/soil-refresh` | fetches soil via `get_soil_info`, stores texture, pH, OC |
| `POST /profile/telegram-link` | generates a 6-digit `link_code`, returns it with the bot username to open and the command `/link CODE` |
| `GET /crops` and `POST /crops` | list and create (crop, area_acres, sowing_date, irrigation_type). Creating also builds and stores the roadmap. |
| `DELETE /crops/{id}` | remove a crop. Only the owner. |
| `GET /crops/{id}/roadmap?lang=` | stages with dates, current stage, localised if the language is not English |
| `POST /crops/{id}/watered` | logs watering and sets `last_watered = today` |
| `GET /today` | one-call dashboard payload: weather summary, per-crop stage, irrigation decision, fertiliser guidance, risk score with reasons, water saved total, unread count |
| `GET /notifications` and `POST /notifications/read-all` | list (latest 50) and mark read |
| `POST /demo/simulate?scenario=heatwave\|heavyrain\|frost\|clear` | sets `demo_scenario`, runs `climate_watch.check_user` immediately, returns created notifications |
| `POST /demo/briefing` | generates and returns today's briefing immediately (for demos) |
| `POST /chat` | same as `/api/advise` but authenticated: automatically injects the farmer's profile (lat, lon, district, state, language, active crop and stage) into the agent's context so the farmer can just ask "should I water today?" |

Validate input with Pydantic models. Return clear JSON errors `{"detail": "..."}`.

Update `app/agent.py` so `advise()` accepts an optional `profile_context` string that is added to the context line. Do not add new agent tools. Pass the already-computed plan summary (crop, stage, day count, today's watering decision, risk score) inside `profile_context`.

---

## 7. Frontend spec

Use the existing green theme (light and dark). Mobile first. Plain HTML and JS. Put shared helpers in `app.js`: `api(path, options)` adds the Bearer header and redirects to `/login` on 401; `speak(text, langCode)` and `listen(langCode)` reuse the existing Web Speech code; language name to speech code map (Marathi mr-IN, Hindi hi-IN, Tamil ta-IN, Telugu te-IN, Kannada kn-IN, Gujarati gu-IN, Bengali bn-IN, Punjabi pa-IN, English en-IN).

**`login.html`:** two tabs, Login and Register. Register form fields: name, username, password, language (dropdown), village, district, state (dropdown of Indian states), and a "Use my GPS" button. Show friendly errors. On success store the token and go to `/dashboard`.

**`dashboard.html`** sections (tab bar at the bottom on mobile):
1. **Today:** greeting with the farmer's name; **Farm Risk Score** gauge with the reasons; weather strip for 7 days (rain mm, tmax/tmin); per crop card showing the stage and day count, **"Water today? Yes/No, X litres"** with the reason, a **"I watered"** button, the fertiliser tip, and a "Read aloud" button that speaks the briefing in the farmer's language; **Water saved** total.
2. **My Crops:** add-crop form (crop, area, sowing date, irrigation type), list of crops, and a **Roadmap timeline** per crop (vertical timeline with dates, the current stage highlighted, water, fertiliser and pest notes, weather warnings in red).
3. **Ask:** the existing chat (text and voice) now calling `/api/chat` with the farmer's profile, plus the **Crop Doctor** photo upload.
4. **Alerts:** notification list with severity colours and a bell badge with the unread count; **Link Telegram** card (shows the code and the exact message to send to the bot); **Demo Mode** card with buttons Heatwave, Heavy rain, Frost, Clear, and "Send today's briefing".
5. **Profile:** edit language, location, soil refresh button, logout.

Poll `/api/notifications` every 60 seconds while the dashboard is open. Show a loading state for every call. Handle network errors with a friendly message. Do not use `localStorage` for anything except the token.

---

## 8. Telegram changes (`bot/telegram_bot.py`)

- Add `/link CODE`: find the user with that `link_code`, set `telegram_chat_id` to the chat id, clear the code, and confirm in the user's language.
- When a linked user sends a question, call `advise()` with the user's profile context and language.
- Keep `/start` and the location button for unlinked users.
- Reuse `notify.send_telegram` for outbound messages.
- If `RUN_BOT_IN_APP=true`, start the bot polling inside the FastAPI `lifespan` (`await application.initialize(); await application.start(); await application.updater.start_polling()` and stop in reverse order on shutdown). **Run polling in only one place at a time** (either the separate process or in-app). Two polling processes with the same token cause a `409 Conflict` error.

---

## 9. Phases (do them in order)

Use the existing virtual environment (`.\venv\Scripts\Activate.ps1`). Start the server with `uvicorn app.main:app --reload` and keep it running while you test. After each phase, commit with git.

### Phase 0: Prepare
1. Read the existing code in `app/`, `bot/`, `web/` to learn the real function names before changing anything.
2. `git add . ; git commit -m "before upgrade"`.
3. Install the new requirements and update `.env.example` and `.env`.
4. **Verify:** the server starts, `http://127.0.0.1:8000/api/health` returns OK, and one old question still gets an answer.

### Phase 1: Database and auth
1. Create `db.py`, `models.py`, `auth.py`, and the register, login, logout and profile routes.
2. Create tables on startup.
3. **Verify:** register a test user, log in, call `GET /api/profile` with the token (200), call it without a token (401), register the same username again (409), wrong password (401).

### Phase 2: Crops and roadmap
1. Create `crop_data.py`, `weather.py` (without demo override yet), the roadmap part of `planner.py`, and the crop routes.
2. **Verify:** create an Onion crop with a sowing date 30 days ago; `GET /api/crops/{id}/roadmap` shows dated stages, with the second stage marked current. Roadmap in Marathi returns translated text or falls back to English without crashing.

### Phase 3: Watering, fertiliser, risk, `/today`
1. Add the irrigation engine, fertiliser guidance, risk score, water saved, `/watered`, and `/today`.
2. **Verify:** `/api/today` returns weather, stage, `water_today`, `litres`, a reason with numbers, fertiliser note and risk score. Mark "watered" and confirm `last_watered` changes and the deficit resets. A `rainfed` crop never recommends watering.

### Phase 4: Alerts, notifications, scheduler, Telegram, demo mode
1. Add `climate_watch.py`, `notify.py`, notification routes, the demo override in `weather.py`, demo routes, the scheduler, and Telegram `/link`.
2. **Verify:** call `POST /api/demo/simulate?scenario=heatwave`: a `danger` notification appears in `GET /api/notifications`. Calling it twice does not create duplicates. `POST /api/demo/briefing` returns a short briefing in the user's language. If a Telegram chat is linked, the message arrives.

### Phase 5: Frontend
1. Build `login.html`, `dashboard.html`, `app.js`, `styles.css` as specified. Keep the old page at `/chat`.
2. **Verify in Chrome:** register, add a crop, see the roadmap, see Today with the gauge and watering card, tap Read aloud, run Demo Mode and watch the alert badge update, log out and confirm the redirect.

### Phase 6: Smoke test
1. Write `scripts/smoke_test.py` using `httpx` against `BASE_URL` (default `http://127.0.0.1:8000`). It registers a random user, logs in, creates a crop, fetches roadmap and today, simulates a heatwave, lists notifications, and asserts the key fields. Print PASS or FAIL lines in plain ASCII.
2. **Verify:** `python scripts/smoke_test.py` prints PASS for every step.

### Phase 7: Deploy readiness
1. Update the README with the new features, setup, demo script and screenshots section.
2. Make sure `requirements.txt` is complete, `.gitignore` excludes `.env` and database files, and `/api/health` works.
3. Render settings: Build `pip install -r requirements.txt`, Start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, environment variables: `GEMINI_API_KEY`, `DATA_GOV_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DATABASE_URL` (a free Postgres from Neon or Supabase, **not** SQLite, because Render's free disk is wiped on every restart), `APP_TIMEZONE`, `RUN_SCHEDULER=true`, `RUN_BOT_IN_APP=true` (and stop the local bot so only one instance polls).
4. Tell the user the free Render service sleeps after 15 minutes idle, which also pauses the scheduler. Recommend a free uptime pinger hitting `/api/health` every 10 minutes during judging.

---

## 10. Known pitfalls and fixes

| Symptom | Cause | Fix |
|---|---|---|
| `UnicodeEncodeError` in the terminal | emoji or Marathi text printed on a cp1252 console | print ASCII only, or set `PYTHONUTF8=1` |
| `ZoneInfoNotFoundError: Asia/Kolkata` | no timezone database on Windows | `pip install tzdata` |
| `sqlite3.ProgrammingError` about threads | SQLite used across threads | `connect_args={"check_same_thread": False}` |
| `NoSuchModuleError: postgres` | URL starts with `postgres://` | rewrite to `postgresql+psycopg2://` |
| Gemini returns text instead of JSON | code fences or extra words | strip fences, `json.loads`, fall back to English |
| Gemini 429 or quota error | too many calls | cache per user per day, catch and fall back |
| Gemini tools plus JSON mode error | the two cannot be combined | no `tools` on JSON calls |
| Duplicate alerts every 3 hours | missing dedupe | use `dedupe_key` |
| Scheduler runs twice in dev | `--reload` spawns two processes | accept in dev, or run with `RUN_SCHEDULER=false` and test jobs through the demo routes |
| Telegram `409 Conflict` | two polling instances | poll in one place only |
| Open-Meteo 400 error | bad parameter name | the ET0 field is `et0_fao_evapotranspiration`, `past_days` max is 92 |
| Soil lookup very slow | SoilGrids latency | 40 s timeout, store the result in the profile, never call it on every request |
| Browser mic or GPS blocked | page not on HTTPS | works on localhost and on Render's HTTPS URL |
| `422 Unprocessable Entity` | request body does not match the Pydantic model | check field names and types in the frontend |

---

## 11. Final acceptance checklist

- [ ] Register and login work, wrong password rejected, token required for private routes
- [ ] Farmer profile (language, location, soil) is saved and persists after a server restart
- [ ] Adding a crop produces a dated roadmap with the current stage highlighted
- [ ] Today screen shows watering yes/no with litres and a reason with numbers
- [ ] Fertiliser tip matches the crop stage and soil flags and ends with the soil-test reminder
- [ ] Risk score and reasons shown
- [ ] Demo Mode creates alerts instantly in the app and on Telegram
- [ ] Morning briefing is generated in the farmer's language and can be read aloud
- [ ] Water saved counter updates
- [ ] Old features (chat, voice, Crop Doctor, Telegram bot) still work
- [ ] `scripts/smoke_test.py` passes
- [ ] README updated, repository public, `.env` not committed
- [ ] Deployed on Render with a hosted Postgres database

## 12. Suggested 3-minute demo script

1. Register as a farmer in Marathi, village Nashik, and add Onion planted 30 days ago.
2. Show the Today screen: risk score, "water today: no, rain tomorrow", fertiliser tip for the leaf growth stage.
3. Open the roadmap timeline.
4. Tap Demo Mode, Heatwave: the alert appears in the app and on the phone through Telegram.
5. Tap "Send briefing" and play the spoken Marathi briefing.
6. Show the Water Saved counter and end with the impact line.
