# KisanSathi (किसान साथी) 🌾
### Multilingual AI Agricultural Advisor for Indian Farmers
**Hackathon Track:** Climate, Resource Infrastructure & Global Supply Resilience

---

## 📌 The Problem
Over 140 million smallholder and marginal farmers across India face critical challenges every day:
- **Climate Volatility & Extreme Weather:** Unseasonal downpours, severe heatwaves, and sudden frost events destroy crops overnight when protective actions are not taken in time.
- **Linguistic & Literacy Barriers:** Most scientific agricultural advisories and government portals are published in English or formal administrative Hindi, inaccessible to farmers speaking regional languages like Marathi, Tamil, Telugu, Kannada, Gujarati, Bengali, or Punjabi.
- **Opaque Market (Mandi) Pricing:** Farmers often sell produce at distressed prices due to a lack of immediate visibility into official wholesale arrival rates and price trends across local and regional APMCs.
- **Fragmented Agronomic Insights:** Weather forecasts, soil properties, pest management, and mandi prices exist in isolated systems without unified, actionable intelligence.

---

## 💡 The Solution
**KisanSathi** is an end-to-end, voice-first multilingual AI agricultural advisor. Farmers simply ask a question by voice or text in their native regional language. 

Powered by **Google Gemini** with automated tool calling, KisanSathi dynamically fetches live weather forecasts, soil parameters, and official mandi prices, reasons over the combined data, and delivers short, plain, and actionable advice with spoken audio. Every recommendation concludes with an explainable 1-line reason citing real data facts.

---

## ✨ Features
1. **Multilingual Voice & Text Advisory:**
   - Supports 9 regional languages: **Marathi, Hindi, Tamil, Telugu, Kannada, Gujarati, Bengali, Punjabi, and English**.
   - Farmers can speak naturally using browser speech recognition or send voice notes on Telegram.
   - Text-to-speech reads answers aloud in the selected language at rural-friendly speeds.
2. **Real-Time Weather Intelligence:**
   - 7-day forecast via Open-Meteo with maximum/minimum temperatures, precipitation volume, and rain probability.
   - Actionable protection: delays pesticide spraying before rain, advises early morning irrigation before heatwaves, and recommends drainage before heavy rain.
3. **Proactive Meteorological Risk Alerts:**
   - Automated detection of **heavy rainfall (≥ 50 mm)**, **heatwaves (≥ 40 °C)**, and **cold frost nights (≤ 6 °C)**.
   - Alerts surfaced immediately in the web UI banner and pushed automatically every 6 hours to Telegram subscribers.
4. **Soil Grids 2.0 Integration:**
   - Hyper-local topsoil composition (clay %, sand %, pH, organic carbon, and texture classification) via ISRIC SoilGrids.
   - Pairs soil characteristics with weather to recommend ideal seasonal crops.
5. **Live APMC Mandi Prices & Price Trends:**
   - Real-time wholesale arrival rates and modal prices from official `data.gov.in` (Agmarknet).
   - Local SQLite snapshot engine (`mandi_history.sqlite3`) tracks 7-day price movements (rising, falling, stable) to answer "Sell now or wait?".
6. **Crop Calendar:**
   - Agronomic seasonal windows (Kharif, Late Kharif, Rabi, Summer) and critical water/protection stages for major crops (Onion, Tomato, Wheat, Soybean, Cotton, Rice, Sugarcane).
7. **Crop Doctor (Photo Disease Diagnosis):**
   - Multimodal Gemini Vision analysis of crop photos taken in the field.
   - Identifies pests, fungal diseases, and nutrient deficiencies and suggests cultural and safe interventions.
8. **Telegram Bot Front End:**
   - Interactive bot (`python -m bot.telegram_bot`) with one-touch GPS location sharing, voice note handling, and proactive alert subscription.

---

## 🛠️ Tech Stack
- **AI Engine:** Google Gemini (via `google-genai` SDK) with automatic function calling & multimodal vision
- **Backend:** Python 3.11+, FastAPI, Uvicorn, httpx, python-dotenv, python-multipart, pydantic, SQLite
- **Frontend:** Vanilla HTML5, CSS3, JavaScript (Web Speech API for Speech Recognition & Speech Synthesis)
- **Messaging:** `python-telegram-bot[job-queue]` v21+
- **Data Integrations:**
  - *Weather:* Open-Meteo 7-day Forecast API
  - *Geocoding:* Open-Meteo Geocoding API & OpenStreetMap Nominatim Reverse Geocoding
  - *Soil Information:* ISRIC SoilGrids 2.0 REST API
  - *Market Prices:* Open Government Data (data.gov.in) Agmarknet Resource

---

## 🔑 Required Environment Variables
Configure the following variable names in your `.env` file (or cloud provider dashboard):

| Variable Name | Description |
| :--- | :--- |
| `GEMINI_API_KEY` | Google Gemini API key from Google AI Studio |
| `GEMINI_MODEL` | Gemini model name (recommended: `gemini-3.5-flash` or `gemini-3.8-flash`) |
| `DATA_GOV_API_KEY` | Free API key from Open Government Data Platform India (data.gov.in) |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather (optional, for Telegram bot) |
| `ALERT_LANGUAGE` | Default language for proactive weather risk alerts (e.g. `Hindi`) |
| `PORT` | Web server port (defaults to `8000`, set dynamically by Render) |

---

## 🚀 Setup & Local Execution

### 1. Clone & Navigate
```bash
git clone https://github.com/yashmane5959/kisansathi.git
cd kisansathi
```

### 2. Create Virtual Environment & Install Dependencies
#### On Windows (PowerShell):
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

#### On Linux / macOS:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Setup Configuration
Copy the template and fill in your keys:
```bash
cp .env.example .env
```

### 4. Run the Web Server Locally
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Open your browser at **http://127.0.0.1:8000**.

### 5. Run the Telegram Bot (Optional)
```bash
python -m bot.telegram_bot
```

---

## ☁️ Deployment on Render

To deploy KisanSathi as a Web Service on [Render](https://render.com):

1. **Repository:** Connect your GitHub repository `https://github.com/yashmane5959/kisansathi.git`.
2. **Environment:** `Python 3`
3. **Build Command:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Start Command:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
   *(Note: The FastAPI lifespan event automatically starts the Telegram bot background polling task in the same process when `TELEGRAM_BOT_TOKEN` is configured, running both the web app and Telegram bot on Render's free tier with zero extra cost).*
5. **Environment Variables:**
   Add `GEMINI_API_KEY`, `DATA_GOV_API_KEY`, `GEMINI_MODEL`, `ALERT_LANGUAGE`, and optionally `TELEGRAM_BOT_TOKEN` in Render's **Environment** tab.

---

## 🧪 Testing Endpoints
```powershell
# Health check
curl http://127.0.0.1:8000/api/health

# Weather risk alerts
curl "http://127.0.0.1:8000/api/alerts?lat=19.99&lon=73.79"

# Marathi agricultural advisory
curl -X POST http://127.0.0.1:8000/api/advise `
  -H "Content-Type: application/json" `
  -d '{"text": "Should I harvest my onions this week?", "district": "Nashik", "language": "Marathi"}'
```

---

## 👏 Credits & Acknowledgments
- **Google Gemini (Google DeepMind):** For high-speed multilingual comprehension, multimodal plant leaf diagnosis, and tool-calling reasoning.
- **Antigravity (Google DeepMind):** For agentic architecture design, tool scaffolding, and rapid full-stack autonomous orchestration.
- **Open-Meteo:** For open-source, hyper-local meteorological forecasts and geocoding services.
- **ISRIC - World Soil Information:** For the global SoilGrids 2.0 REST API dataset.
- **OpenStreetMap & Nominatim:** For open reverse-geocoding data.
- **Open Government Data (OGD) Platform India (data.gov.in):** For official Agmarknet wholesale agricultural commodity market feeds.
- **FastAPI & Starlette:** For high-performance async Python backend framework.
- **python-telegram-bot:** For the Telegram farmer interaction interface.
- **Web Speech API (W3C):** For zero-dependency, in-browser multilingual speech recognition and text-to-speech synthesis.

---

## ⚖️ Disclaimer
KisanSathi is designed to provide timely agronomic and meteorological advisory. Farmers must always verify specific chemical, pesticide, and fertilizer dosages with their local **Krishi Vigyan Kendra (KVK)** or state agricultural extension officers before application.
