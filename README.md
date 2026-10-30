# AI Voice Receptionist

[![GitHub](https://img.shields.io/badge/GitHub-Dental--Voice--Assistant-blue?style=for-the-badge&logo=github)](https://github.com/diorwave/Dental-Voice-Assistant)
[![Stars](https://img.shields.io/github/stars/diorwave/Dental-Voice-Assistant?style=for-the-badge&logo=github)](https://github.com/diorwave/Dental-Voice-Assistant/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Django](https://img.shields.io/badge/Django-5.1-092E20?style=for-the-badge&logo=django)](https://www.djangoproject.com/)
[![OpenAI](https://img.shields.io/badge/OpenAI-gpt--4o-412991?style=for-the-badge&logo=openai)](https://platform.openai.com/)

An AI-powered phone receptionist that answers calls 24/7, books appointments on Google Calendar, and sends SMS confirmations — built with **Django**, **OpenAI**, **Vapi**, and **Google Calendar**. Ships with a web frontend: a landing page with a live voice widget, a chat tester, and a staff dashboard.

## What It Does

- Answers incoming phone calls with a natural-sounding AI voice ("Sarah")
- Checks Google Calendar availability in real time
- Books appointments and creates calendar events
- Sends SMS confirmations via Twilio
- Logs every call and appointment to the database (Django admin + a custom dashboard)
- Includes a **web frontend**: landing page, browser voice call with **live transcript**, and a text chat tester

## Tech Stack

| Component | Role |
|-----------|------|
| **Django** | Backend brain — hosts the LLM agent, tools, prompts, admin, and frontend |
| **OpenAI (`gpt-4o`)** | AI conversation engine — decides actions and calls tools |
| **Vapi** | Voice transport — phone numbers, speech-to-text, text-to-speech only |
| **Google Calendar API** | Appointment availability and booking |
| **Twilio** | SMS confirmations |
| **SQLite / PostgreSQL** | Call logs and appointment records (SQLite for local dev, Postgres for Docker/production) |

## Architecture

Vapi is used **only** as a voice transport layer (STT/TTS). All AI logic, tools, and prompts live in Django.

```
[Phone Call] → [Vapi: STT only] → [Django Custom LLM Endpoint]
                                          ↓
                                   [OpenAI + Tools]
                                    ↙     ↓      ↘
                         [Google Cal] [Twilio] [Database]
                                          ↓
                                   [Django Response]
                                          ↓
                              [Vapi: TTS only] → [Caller hears response]
```

### How It Works

1. Caller dials the phone number (via Vapi)
2. Vapi converts speech to text and sends it to Django's `/api/vapi/chat/completions/` endpoint
3. Django calls the OpenAI API with the system prompt and tool definitions
4. The model decides what to do — check calendar, book appointment, send SMS, etc.
5. Django executes tools locally and returns the final response to Vapi
6. Vapi converts the text response back to speech for the caller

## Web Frontend

Beyond the phone line, the app serves a browser UI (Django templates — no build step):

| Page | URL | What it is |
|------|-----|-----------|
| **Landing** | `/` | Marketing page with a live **voice call** widget (opens a window that shows the running transcript of both caller and Sarah) |
| **Chat with Sarah** | `/chat/` | Text chat tester — drives the same agent, calendar, and booking the phone line uses |
| **Dashboard** | `/dashboard/` | Login-protected staff view — KPI cards (calls, bookings, conversion) plus appointment and call-log tables |
| **Django Admin** | `/admin/` | Raw record management |

The voice widget needs `VAPI_PUBLIC_KEY` and `VAPI_ASSISTANT_ID` set (see below); the chat tester only needs `OPENAI_API_KEY`.

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/diorwave/Dental-Voice-Assistant.git
cd Dental-Voice-Assistant
cp .env.example .env
```

### 2. Generate a Django secret key

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

Paste the output into `.env` as `SECRET_KEY`.

### 3. Fill in `.env`

```dotenv
SECRET_KEY=your-generated-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,*

# Use a local SQLite file (no Postgres/Docker needed). Leave blank to use Postgres below.
USE_SQLITE=True

OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o                 # or gpt-4o-mini for lower cost / latency

VAPI_API_KEY=your-vapi-private-key
VAPI_PUBLIC_KEY=your-vapi-public-key      # browser voice widget
VAPI_ASSISTANT_ID=your-vapi-assistant-id  # browser voice widget

GOOGLE_CALENDAR_CREDENTIALS=google-calendar-credentials.json
GOOGLE_CALENDAR_ID=your-calendar-id@group.calendar.google.com

TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...
```

**Where to get keys:**
- **OpenAI:** [platform.openai.com/api-keys](https://platform.openai.com/api-keys) (make sure billing/credits are set up)
- **Vapi:** [dashboard.vapi.ai](https://dashboard.vapi.ai) — the **public** key and assistant ID are for the web voice widget
- **Google Calendar:** see setup below
- **Twilio:** [twilio.com/console](https://www.twilio.com/console)

### 4. Google Calendar setup

<details>
<summary>Create a service account and share your calendar (click to expand)</summary>

1. **Create a Google Cloud project** — [Google Cloud Console](https://console.cloud.google.com) → **New Project**.
2. **Enable the Calendar API** — APIs & Services → Library → search **"Google Calendar API"** → **Enable**.
3. **Create service-account credentials** — APIs & Services → Credentials → **+ Create Credentials → Service Account** → name it → **Done**. Open it → **Keys** tab → **Add Key → Create new key → JSON**. Move the downloaded file to the project root:
   ```bash
   mv ~/Downloads/your-file.json ./google-calendar-credentials.json
   ```
4. **Get your Calendar ID** — [Google Calendar](https://calendar.google.com) → your calendar's **Settings and sharing → Integrate calendar → Calendar ID**. For your primary calendar it's just your Gmail address.
5. **Share the calendar with the service account** — copy the `client_email` from the JSON, then in Calendar → **Share with specific people → + Add people** → paste it → set **Make changes to events** → **Send**.

> Without step 5 (write access), the agent can *read* availability but booking fails with a 403.
</details>

### 5. Run it

**Option A — locally with SQLite (simplest):**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
USE_SQLITE=True python manage.py migrate
USE_SQLITE=True python manage.py createsuperuser      # for the dashboard/admin
USE_SQLITE=True python manage.py runserver 0.0.0.0:8000
```

**Option B — Docker Compose with PostgreSQL** (leave `USE_SQLITE` blank in `.env`):

```bash
docker compose up --build
docker compose exec web python manage.py createsuperuser
```

Both serve on `http://localhost:8000`. Open `/` for the landing page, `/chat/` to test, `/dashboard/` for staff.

### 6. Verify it works

```bash
# Health check
curl http://localhost:8000/api/vapi/webhook/
# → {"status": "ok", "service": "AI Voice Receptionist"}

# The agent endpoint (OpenAI-format request/response)
curl -X POST http://localhost:8000/api/vapi/chat/completions/ \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What times are open tomorrow?"}]}'
```

### 7. Expose with ngrok (for Vapi)

```bash
ngrok http 8000        # copy the https://...ngrok-free.app URL
```

### 8. Connect Vapi

1. [Vapi Dashboard](https://dashboard.vapi.ai) → create an Assistant.
2. **Model → Custom LLM**, and set the **base URL** (Vapi appends `/chat/completions` itself):
   ```
   https://your-ngrok-url.ngrok-free.app/api/vapi
   ```
3. **Server URL** (end-of-call reports):
   ```
   https://your-ngrok-url.ngrok-free.app/api/vapi/webhook/
   ```
4. Assign a phone number, or use **Talk to Assistant** (web mic) to test.

> **Important:** the Custom LLM URL is the **base** (`/api/vapi`), not the full `/chat/completions/` path — Vapi appends that. Django then calls OpenAI, runs the tools, and returns the reply. Vapi only handles voice (STT/TTS).

## Project Structure

```
ai-voice-agent/
├── receptionist_project/
│   ├── settings.py              # Django config (SQLite toggle, CSRF, keys)
│   └── urls.py                  # Root URL routing
├── calls/
│   ├── models.py                # CallLog + Appointment models
│   ├── views.py                 # Custom LLM endpoint + Vapi webhook (API)
│   ├── frontend_views.py        # Landing, chat, dashboard (HTML)
│   ├── urls.py                  # API + frontend routes
│   ├── admin.py                 # Django admin registration
│   ├── templates/               # base, landing, chat, dashboard, chat widget
│   ├── agent/
│   │   ├── receptionist.py      # OpenAI agentic loop (the brain)
│   │   ├── tools.py             # OpenAI tool schemas (availability, booking, end call)
│   │   └── prompts.py           # System prompt (Sarah @ Bright Smile Dental)
│   └── services/
│       ├── calendar.py          # Google Calendar API
│       ├── sms.py               # Twilio booking confirmations (server-side only)
│       └── database.py          # Call logging
├── docker-compose.yml
├── Dockerfile
├── .env.example
└── requirements.txt
```

### Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/vapi/chat/completions/` | Custom LLM — receives messages from Vapi, calls OpenAI + tools, returns an OpenAI-format response |
| `POST /api/vapi/webhook/` | Webhook — receives end-of-call reports, logs calls to the DB |
| `GET /api/vapi/webhook/` | Health check |
| `GET /`, `/chat/`, `/dashboard/` | Frontend pages |

## Deploy to Production

```bash
# Railway (Postgres) — leave USE_SQLITE unset
railway init
railway add --plugin postgresql
railway up
```

Set your environment variables in the host dashboard, then update the Vapi Custom LLM base URL and Server URL to your deployed domain.

## License

MIT
