# KisanSathi (किसान साथी) 🌾
### Multilingual AI Agricultural Advisor for Indian Farmers
**Hackathon Track:** Climate, Resource Infrastructure & Global Supply Resilience

---

## 📖 Project Overview
**KisanSathi** is an end-to-end multilingual AI decision platform for Indian farmers. It bridges critical information gaps by translating real-time meteorological, soil, and agricultural market intelligence into simple, spoken, actionable guidance in 9 Indian regional languages (**Marathi, Hindi, Tamil, Telugu, Kannada, Gujarati, Bengali, Punjabi, and English**).

Powered by **Google Gemini** with automatic function calling, KisanSathi dynamically calls live APIs to:
1. **Suggest Seasonal Crops:** Matches local soil texture and pH from ISRIC SoilGrids with 7-day rainfall forecasts.
2. **Optimize Sowing & Harvesting Timings:** Provides timing advice to protect crops from rain or frost.
3. **Protect Crops:** Delivers meteorological safety warnings (delaying pesticide spraying before rain, early irrigation before heatwaves, field drainage).
4. **Sell vs. Wait Intelligence:** Pulls real-time APMC Mandi modal prices from `data.gov.in` (Agmarknet) to advise whether to sell immediately or store.
5. **Explainability:** Concludes every recommendation with a 1-line reason citing actual weather and price figures.
6. **Price Trend Tracking:** Stores daily mandi price snapshots in a local SQLite database to compute 7-day price movements (rising, falling, stable).
7. **Crop Calendar:** Sowing and harvesting windows for major Indian staples (Onion, Tomato, Wheat, Soybean, Cotton, Rice, Sugarcane).
8. **Crop Doctor (Photo Diagnosis):** Multimodal plant disease & pest identification from leaf photos.
9. **Proactive Alerts:** 6-hourly early warnings for extreme weather (heatwaves ≥ 40 °C, heavy downpours ≥ 50 mm, frost nights ≤ 6 °C) via Web UI and Telegram.

---

## 🚀 How to Run on Localhost (Step-by-Step)

### Step 1: Open Terminal in Project Directory
Open **PowerShell** or **Command Prompt** (on Windows) or **Terminal** (on macOS / Linux) and navigate to the project directory:

```bash
cd kisansathi
```

---

### Step 2: Create and Activate Virtual Environment

#### On Windows (PowerShell):
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
*(If you see an execution policy error, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and retry).*

#### On Windows (Command Prompt - cmd.exe):
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

#### On macOS / Linux:
```bash
python3 -m venv venv
source venv/bin/activate
```

---

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

---

### Step 4: Configure API Keys (.env)
Create or check your `.env` file in the `kisansathi/` directory:

```env
# Google Gemini API Key (Get at https://aistudio.google.com/apikey)
GEMINI_API_KEY=your_gemini_api_key_here

# Recommended Gemini Model: gemini-3.5-flash or gemini-3.8-flash
GEMINI_MODEL=gemini-3.5-flash

# Open Government Data India API Key (Free at https://data.gov.in)
DATA_GOV_API_KEY=your_data_gov_api_key_here

# Telegram Bot Token from @BotFather (optional, required only for Telegram bot)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Default language for proactive weather alerts
ALERT_LANGUAGE=Hindi
```

---

### Step 5: Start the Web Server on Localhost
Run Uvicorn to start the local web application:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

You should see:
```text
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

---

### Step 6: Open KisanSathi in Your Browser
Open your browser (Google Chrome or Edge recommended for speech features) and go to:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

#### What you can try in the Web UI:
1. **Select Language:** Choose **मराठी (Marathi)**, **हिंदी (Hindi)**, or any of the 9 regional languages.
2. **GPS or District:** Click **"📡 GPS"** to detect your farm's location, or type `Nashik`, `Baramati`, `Kurnool`, etc.
3. **Ask a Farming Question:**
   - Type or tap the quick chips: *"Should I harvest my onions this week?"*
   - Or click **"🎤 Speak Question"** to ask by voice in your native language!
4. **Instant Spoken Advice:** KisanSathi answers in simple regional words and automatically speaks the response aloud using text-to-speech.
5. **Scan Crop Disease (Photo Diagnosis):** Click **"📷 Scan Crop Disease"**, upload a photo of a crop leaf or pest, and click **"🩺 Diagnose"** to receive instant AI treatment suggestions.
6. **Price Trends & Crop Calendar:** Ask questions like *"Is the price of onion rising or falling?"* or *"When should I sow wheat in Maharashtra?"*.

---

### Step 7: (Optional) Run the Telegram Bot
In a separate terminal window (with the virtual environment activated):

```bash
cd kisansathi
python -m bot.telegram_bot
```

1. Open Telegram and search for your bot (or [@kisansathi01bot](https://t.me/kisansathi01bot)).
2. Send `/start` and tap **"📍 Share my location"**.
3. Send any question by text or **send a voice message in your native language**.
4. Send `/subscribe` to enroll in automatic 6-hourly proactive risk alerts.

---

## 🧪 Testing Endpoints Locally via Command Line

You can test individual endpoints directly with curl or PowerShell:

#### 1. System Health Check
```powershell
curl http://127.0.0.1:8000/api/health
```

#### 2. Weather Risk Alerts Check
```powershell
curl "http://127.0.0.1:8000/api/alerts?lat=19.99&lon=73.79"
```

#### 3. Agricultural Advisory Query
```powershell
curl -X POST http://127.0.0.1:8000/api/advise `
  -H "Content-Type: application/json" `
  -d '{"text": "Should I harvest my onions this week?", "district": "Nashik", "language": "Marathi"}'
```

---

## 📁 Project Architecture & Folder Structure
```text
kisansathi/
│
├── app/
│   ├── __init__.py
│   ├── config.py           # Loads environment variables & settings singleton
│   ├── tools.py            # Real-time tool definitions (weather, soil, mandi, trend, calendar)
│   ├── agent.py            # Gemini AI agent with AFC tools and multimodal vision
│   ├── alerts.py           # Meteorological risk engine (heatwave, heavy rain, cold night)
│   └── main.py             # FastAPI REST routes and index.html serving
│
├── bot/
│   ├── __init__.py
│   └── telegram_bot.py     # Telegram bot with voice note processing & alert subscription
│
├── web/
│   ├── index.html          # Mobile-first responsive UI (voice recognition & speech synthesis)
│   └── static/             # Static assets folder
│
├── mandi_history.sqlite3   # Local SQLite database for snapshot price trends
├── requirements.txt        # Python dependency manifest
├── .env                    # Active configuration and secrets (not committed to git)
├── .env.example            # Template for environment configuration
├── .gitignore              # Git ignore rules
└── README.md               # Complete setup, run instructions, and documentation
```

---

## 🛠️ Data Sources & Integrations
| Source | Service / API | Purpose |
| :--- | :--- | :--- |
| **Open-Meteo** | Forecast & Geocoding API | 7-day temperature, precipitation sum & probability, coordinate lookup |
| **OpenStreetMap** | Nominatim Reverse Geocoding | Resolves coordinates to Indian state and district (needed for mandi lookups) |
| **ISRIC** | SoilGrids 2.0 REST API | Topsoil properties (clay %, sand %, pH, organic carbon, texture classification) |
| **data.gov.in** | Agmarknet Daily Market Resource | Live official wholesale modal prices and daily arrivals |
| **Google Gemini** | `google-genai` SDK | Reasoning, regional multilingual translation, and multimodal plant vision |

---

## ⚠️ Notes & Agronomic Considerations
1. **Mandi Data Constraints:** Agmarknet provides wholesale daily arrivals. If a specific local market has no arrivals recorded on a given day, KisanSathi automatically queries broader state markets and provides regional averages.
2. **Speech Recognition in Browsers:** Web Speech Recognition runs natively in Chromium-based browsers (Google Chrome, Microsoft Edge, Brave) with microphone permissions enabled.
3. **Pesticide Advisory:** KisanSathi advises on meteorological safety (e.g. delaying spray before rainfall to avoid runoff). Farmers must always verify specific chemical dosages with their local Krishi Vigyan Kendra (KVK).
