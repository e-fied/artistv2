# 🎤 Tour Tracker v2

An automated, AI-powered background scraping agent and web dashboard designed to discover, extract, and track comedy and music artist tour dates. Tour Tracker monitors Ticketmaster, official artist websites, and manually-added URLs for new events near your configured locations — then sends real-time Telegram notifications when confirmed matches are found.

Built for self-hosting on an Unraid NAS (or any Docker host).

---

## Table of Contents

- [Features](#features)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
  - [Scan Pipeline](#scan-pipeline)
  - [Data Flow Diagram](#data-flow-diagram)
  - [Database Schema](#database-schema)
- [Dashboard & UI Pages](#dashboard--ui-pages)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation & Deployment](#installation--deployment)
  - [1. Clone the Repository](#1-clone-the-repository)
  - [2. Configure Environment Variables](#2-configure-environment-variables)
  - [3. Build & Deploy with Docker Compose](#3-build--deploy-with-docker-compose)
  - [4. Verify the Deployment](#4-verify-the-deployment)
- [API Keys & External Services](#api-keys--external-services)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [Runtime Settings (UI)](#runtime-settings-ui)
- [Docker Architecture](#docker-architecture)
- [Development Workflow](#development-workflow)
  - [Local Setup](#local-setup)
  - [Deploy → Test Cycle](#deploy--test-cycle)
  - [Running Tests](#running-tests)
- [Key Design Decisions](#key-design-decisions)
- [Known Limitations & Gotchas](#known-limitations--gotchas)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Features

### 🔍 Intelligent Web Scraping
Uses [Crawl4AI](https://github.com/unclecode/crawl4ai) — a self-hosted headless Chromium sidecar — to render JavaScript-heavy artist websites and extract their raw content as Markdown. Falls back to [Firecrawl](https://firecrawl.dev) (cloud API) automatically if the local crawler fails.

For dynamic tour pages that only expose dates through client-side widgets or embedded APIs, Tour Tracker can enrich the crawled markdown with event data fetched directly from supported vendors such as Seated, Punchup, and Upnex / LeadConnector event portals before sending content to Gemini.

### 🤖 AI-Powered Extraction
Leverages **Google Gemini 2.5 Flash** with structured JSON output (`response_schema`) to parse messy, inconsistent website text into clean event objects with dates, venues, cities, and ticket links. The schema guarantees parseable results — no regex hacks.

### 🎯 Auto-Discovery
Automatically locates an artist's official tour page using Gemini with **Google Search Grounding**. Just add an artist name and Tour Tracker will find their website for you.

### 🎫 Ticketmaster Integration
Queries the **Ticketmaster Discovery API** by either attraction ID (precise) or keyword (fallback) to find upcoming events. Geo-filters results against your location profiles with configurable radius.

### 📍 Location-Based Matching
A three-tier matching system determines whether a discovered event is "near" you:

1. **Exact city match** → confidence `1.0`
2. **Alias match** (e.g. "Burnaby" → "Vancouver") → confidence `0.95`
3. **Haversine geo-radius** (lat/lon distance calculation) → confidence `0.7–1.0` scaled by proximity

### 🔁 Idempotent Deduplication
SHA-256 hashing of `artist_id|event_name|venue|city|date` prevents duplicate entries. Re-discoveries of the same event update mutable fields (ticket URL, evidence) but **never downgrade** status — once an event is confirmed, it stays confirmed.

### 📲 Telegram Notifications
Instant HTML-formatted alerts when new confirmed events are found near your locations. Optional digest summaries for "possible" events that need manual review.

### 📊 Full Dashboard
A server-rendered web UI with:
- **Dashboard** — aggregate stats, per-artist health summaries, last scan time
- **Events** — filterable list of all discovered events, status badges
- **Review inbox** — confirm or reject "possible" events manually
- **Scan history** — detailed logs of every scan run with per-source results
- **Source health** — monitor which crawl sources are failing
- **Location management** — add/edit location profiles and city aliases
- **Real-time log tailing** — watch background processes live in the browser
- **Settings** — configure scan interval, notifications, and timezone from the UI

### ⏱ Scheduled Background Scanning
APScheduler runs scans at a configurable interval (default: every 6 hours). Supports manual triggers from the UI for individual artists or all artists at once.

---

## How It Works

1. **You add artists** — provide a name and optionally link their Ticketmaster attraction ID or official website URL. Or let Auto-Discovery find their site.
2. **The scheduler fires** — every N hours, the scan pipeline runs for all non-paused artists.
3. **Data sources are queried** — Ticketmaster API, crawled websites, and manual URLs are all checked.
4. **Events are extracted** — Gemini parses raw web content into structured event data.
5. **Location matching** — each event is checked against your location profiles (city names, aliases, geo-radius).
6. **Deduplication** — known events are updated; new events are inserted with `confirmed` or `possible` status.
7. **Notifications fire** — confirmed events trigger an instant Telegram message. Possible events are batched into a review summary.
8. **You review** — open the dashboard to confirm, reject, or inspect events.

When a site is mostly a shell page, the crawler may first append structured event data from supported widget vendors so Gemini sees the actual dates instead of just the shell copy.

---

## Tech Stack

| Layer              | Technology                                                                  |
| ------------------ | --------------------------------------------------------------------------- |
| **Language**       | Python 3.12                                                                 |
| **Web Framework**  | FastAPI (ASGI, Uvicorn, single worker)                                      |
| **Templating**     | Jinja2 (server-rendered HTML with template inheritance)                     |
| **Frontend**       | Vanilla CSS · Alpine.js (interactivity) · HTMX (partial page updates)      |
| **Database**       | SQLite (WAL mode) via SQLAlchemy 2.x (`Mapped[]`, `mapped_column`, `DeclarativeBase`) |
| **Scheduler**      | APScheduler `BackgroundScheduler` with SQLAlchemy job store                 |
| **LLM**            | Google Gemini 2.5 Flash (`google-genai` SDK, structured JSON output)        |
| **Web Scraping**   | Crawl4AI (Docker sidecar, headless Chromium) + Firecrawl (cloud fallback)   |
| **Event API**      | Ticketmaster Discovery API v2                                               |
| **Notifications**  | Telegram Bot API (HTML-formatted messages)                                  |
| **HTTP Client**    | httpx (async-capable, used for all external API calls)                      |
| **Containerization** | Docker + Docker Compose (two services)                                    |

### No Build Step
There is no npm, no Webpack, no Tailwind, and no bundler. All CSS and JS is served directly from `/static/`. Alpine.js and HTMX are loaded from CDN.

---

## Architecture

### Scan Pipeline

```
APScheduler (every N hours)
  └─▶ scanner.scan_all_artists()
       ├─▶ For each active (non-paused) Artist:
       │    ├─▶ [Ticketmaster Source]
       │    │    └─ TicketmasterClient
       │    │         ├─ search_events_by_attraction(attraction_id, latlong, radius)
       │    │         └─ search_events_by_keyword(name) — fallback if no attraction ID
       │    │
       │    ├─▶ [Web Sources] (official_website, manual_url)
       │    │    ├─ CrawlerService.fetch_markdown(url)
       │    │    │   ├─ Try Crawl4AI sidecar (http://crawl4ai:11235/crawl)
       │    │    │   └─ Fallback to Firecrawl cloud API
       │    │    ├─ CrawlerService.clean_markdown() → cap at 50k chars
       │    │    └─ ExtractorService.extract_events() → Gemini structured JSON
       │    │
       │    └─▶ _process_event() for each discovered event:
       │         ├─ location_matcher.match_event_to_locations()
       │         ├─ dedup.upsert_event() — SHA-256 key, never downgrade status
       │         └─ notifier.send_telegram() — if new + confirmed
       │
       └─▶ Record ScanRun + ScanSourceResult history
```

### Data Flow Diagram

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│ Ticketmaster │     │ Artist Sites │     │ Manual URLs      │
│ Discovery API│     │ (crawled)    │     │ (crawled)        │
└──────┬───────┘     └──────┬───────┘     └────────┬─────────┘
       │                    │                       │
       │              ┌─────▼─────┐                 │
       │              │ Crawl4AI  │◄────────────────┘
       │              │ Sidecar   │
       │              └─────┬─────┘
       │                    │ (fallback)
       │              ┌─────▼──────┐
       │              │ Firecrawl  │
       │              │ Cloud API  │
       │              └─────┬──────┘
       │                    │ Markdown
       │              ┌─────▼──────┐
       │              │ Gemini 2.5 │
       │              │ Flash LLM  │
       │              └─────┬──────┘
       │                    │ Structured JSON
       ▼                    ▼
  ┌─────────────────────────────────┐
  │       Location Matcher          │
  │  exact_city → alias → haversine│
  └──────────────┬──────────────────┘
                 │
  ┌──────────────▼──────────────────┐
  │       Dedup / Upsert            │
  │  SHA-256 key, status priority   │
  └──────────────┬──────────────────┘
                 │
  ┌──────────────▼──────────────────┐
  │       SQLite Database           │
  │  (WAL mode, /app/data/)        │
  └──────────────┬──────────────────┘
                 │
  ┌──────────────▼──────────────────┐
  │     Telegram Notifications      │
  │  (confirmed events + digests)   │
  └──────────────┬──────────────────┘
                 │
  ┌──────────────▼──────────────────┐
  │        Web Dashboard            │
  │  FastAPI + Jinja2 + HTMX       │
  └─────────────────────────────────┘
```

### Database Schema

```
Artist (1) ──▶ (N) ArtistSource         ticketmaster | official_website | manual_url
Artist (1) ──▶ (N) ArtistLocation       links to LocationProfile (home vs travel)
Artist (1) ──▶ (N) Event                discovered events
Artist (1) ──▶ (N) ScanRun              scan execution history

Event (1)  ──▶ (N) EventReview          user confirm/reject actions

LocationProfile (1) ──▶ (N) LocationAlias   e.g. "Burnaby" → "Vancouver"

ScanRun (1)  ──▶ (N) ScanSourceResult   per-source results within a scan

AppSetting                               key-value store for runtime config
```

#### Key Models

| Model | Table | Purpose |
| --- | --- | --- |
| `Artist` | `artists` | Artist name, type (music/comedy), TM attraction ID, pause state |
| `ArtistSource` | `artist_sources` | Data source per artist — URL, fetch mode, failure tracking, content hash |
| `ArtistLocation` | `artist_locations` | Many-to-many link between artists and location profiles |
| `Event` | `events` | Discovered event — name, venue, city, date, status, dedup key, confidence |
| `EventReview` | `event_reviews` | User review action log (confirm/reject/ignore) |
| `LocationProfile` | `location_profiles` | Tracked region — name, lat/lon, radius, country code |
| `LocationAlias` | `location_aliases` | City names within a location profile (e.g. suburbs) |
| `ScanRun` | `scan_runs` | Scan execution record — trigger, status, event counts |
| `ScanSourceResult` | `scan_source_results` | Per-source result per scan — success, error, duration, events extracted |
| `AppSetting` | `app_settings` | Key-value settings store |

---

## Dashboard & UI Pages

| Page | URL | Description |
| --- | --- | --- |
| **Dashboard** | `/` | Overview — confirmed/possible event counts, per-artist summaries with source health, last scan time |
| **Add Artist** | `/artists/new` | Search Ticketmaster for attraction ID, add name + type, auto-find tour page |
| **Artist Detail** | `/artists/{id}` | Edit artist, manage sources, view linked events, trigger manual scan |
| **Events** | `/events` | Filterable list of all discovered events with status badges and confidence scores |
| **Review Inbox** | `/review` | Confirm or reject "possible" events — badge count in sidebar |
| **Scan History** | `/scans` | Timestamped log of every scan run with per-source breakdown |
| **Source Health** | `/sources/health` | Monitor failing sources (3+ consecutive failures highlighted) |
| **Locations** | `/locations` | Add/edit location profiles, manage city aliases, set default vs per-artist locations |
| **System Logs** | `/logs` | Real-time log tailing — watch the scanner, crawler, and extractor in action |
| **Settings** | `/settings` | Configure scan interval, timezone, notification preferences, API key status |
| **Health Check** | `/health` | JSON endpoint for Docker healthcheck (`{"status": "ok"}`) |

---

## Project Structure

```
artistv2/
├── main.py                     # FastAPI app factory, lifespan hooks, router registration
├── Dockerfile                  # Python 3.12-slim, non-root user, port 8000
├── docker-compose.yml          # tourtracker + crawl4ai services
├── requirements.txt            # Python dependencies
├── .env.example                # Template for secrets
├── .gitignore                  # Excludes data/, .env, __pycache__, etc.
├── AGENTS.md                   # Context file for AI coding agents
│
├── app/
│   ├── __init__.py
│   ├── config.py               # AppSettings (Pydantic), load_settings(), save_settings()
│   ├── database.py             # SQLAlchemy engine (SQLite WAL), SessionLocal, get_db()
│   ├── scheduler.py            # APScheduler BackgroundScheduler with SQLAlchemy job store
│   ├── seed.py                 # Default data: Vancouver/Lower Mainland + 19 alias cities
│   │
│   ├── models/                 # SQLAlchemy ORM models (DeclarativeBase, Mapped[], mapped_column)
│   │   ├── __init__.py         # Re-exports: Artist, ArtistSource, ArtistLocation, Event, EventReview,
│   │   │                       #   LocationProfile, LocationAlias, ScanRun, ScanSourceResult, AppSetting
│   │   ├── artist.py           # Artist, ArtistSource, ArtistLocation
│   │   ├── event.py            # Event, EventReview
│   │   ├── location.py         # LocationProfile, LocationAlias
│   │   ├── scan.py             # ScanRun, ScanSourceResult
│   │   └── settings.py         # AppSetting (key-value store)
│   │
│   ├── schemas/                # Pydantic schemas for external data
│   │   ├── __init__.py
│   │   └── gemini.py           # ExtractedEvent, ExtractionResult, ConfidenceLevel enum
│   │
│   ├── services/               # Business logic (stateless, no HTTP concerns)
│   │   ├── __init__.py
│   │   ├── scanner.py          # Scan orchestrator: scan_all_artists(), _scan_single_artist(),
│   │   │                       #   _process_event(), notification dispatch
│   │   ├── crawler.py          # CrawlerService: Crawl4AI HTTP → Firecrawl fallback,
│   │   │                       #   clean_markdown(), hash_content()
│   │   ├── extractor.py        # ExtractorService: Gemini structured extraction from markdown
│   │   ├── autofind.py         # auto_find_tour_page() — Gemini + Google Search grounding
│   │   ├── dedup.py            # make_dedup_key() (SHA-256), upsert_event() (status-aware)
│   │   ├── location_matcher.py # haversine_km(), match_event_to_locations(), get_profiles_for_artist()
│   │   ├── ticketmaster.py     # TicketmasterClient: attraction search, event search, geo-filtering
│   │   └── notifier.py         # send_telegram(), format_event_notification(), format_review_summary()
│   │
│   ├── routes/                 # FastAPI routers (thin controllers → delegate to services)
│   │   ├── __init__.py
│   │   ├── dashboard.py        # GET /
│   │   ├── artists.py          # /artists/* — CRUD, TM search, auto-find
│   │   ├── events.py           # /events/* — listing, filtering, status updates
│   │   ├── locations.py        # /locations/* — profile CRUD, alias management
│   │   ├── settings_routes.py  # /settings — view/update configuration
│   │   ├── scans.py            # /scans — scan history, manual trigger
│   │   ├── sources.py          # /sources/* — artist source management
│   │   ├── logs.py             # /logs — real-time log tailing endpoint
│   │   └── health.py           # GET /health — container healthcheck
│   │
│   ├── templates/              # Jinja2 HTML templates (all extend base.html)
│   │   ├── base.html           # Base layout: sidebar nav, CSS/JS includes, main content area
│   │   ├── dashboard.html      # Dashboard with stat cards and artist summary table
│   │   ├── artists/            # Artist list, detail, TM search modal, add/edit forms
│   │   ├── events/             # Event list with status filters
│   │   ├── locations/          # Location profile editor, alias management
│   │   ├── settings/           # Settings form
│   │   ├── scans/              # Scan history table
│   │   ├── sources/            # Source health table
│   │   ├── logs/               # Log viewer
│   │   └── review/             # Event review inbox
│   │
│   └── static/
│       └── css/
│           └── style.css       # Complete design system (~22KB) — dark theme, sidebar layout,
│                               #   cards, tables, badges, forms, responsive design
│
├── data/                       # Runtime data (git-ignored, Docker volume-mounted)
│   ├── tourtracker.db          # SQLite database
│   ├── settings.json           # Non-secret settings persisted from UI
│   └── logs/
│       └── app.log             # Application log file
│
└── tests/
    ├── test_dedup.py           # Dedup key generation and collision tests
    └── test_location_matcher.py # Haversine distance + city/alias matching tests
```

---

## Prerequisites

- **Docker** and **Docker Compose** installed on your server
- API keys for the services you want to use (see [API Keys](#api-keys--external-services))
- A **Telegram Bot** (optional — for notifications)

---

## Installation & Deployment

### 1. Clone the Repository

SSH into your host (Unraid server, VPS, or any Docker host):

```bash
git clone https://github.com/e-fied/artistv2.git /mnt/user/appdata/artistv2
cd /mnt/user/appdata/artistv2
```

> **Unraid users:** Clone into `/mnt/user/appdata/` so data persists across array operations.

### 2. Configure Environment Variables

```bash
cp .env.example .env
nano .env   # or vim, or your preferred editor
```

Fill in your API keys:

```env
# Required for core functionality
GEMINI_API_KEY=your-gemini-api-key

# Required for Ticketmaster event search
TICKETMASTER_API_KEY=your-tm-api-key

# Optional — cloud crawler fallback (free tier available)
FIRECRAWL_API_KEY=your-firecrawl-key

# Optional — Telegram notifications
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id

# Optional overrides
CRAWL4AI_BASE_URL=http://crawl4ai:11235    # default, usually don't change
APP_TIMEZONE=America/Vancouver              # your local timezone
SCAN_INTERVAL_HOURS=6                       # hours between automatic scans
```

### 3. Build & Deploy with Docker Compose

```bash
docker compose up --build -d
```

This starts two containers:

| Container | Purpose | Port |
| --- | --- | --- |
| `TourTracker` | Main FastAPI application | `5001` (external) → `8000` (internal) |
| `TourTracker-Crawl4AI` | Headless Chromium browser for web scraping | Internal only (`11235`) |

> **Note:** The Crawl4AI container takes ~30-45 seconds to start (Chromium initialization). The main app waits for it to be healthy before starting.

### 4. Verify the Deployment

```bash
# Check both containers are running
docker compose ps

# Check the main app logs
docker compose logs tourtracker --tail=50

# Check the crawler sidecar logs
docker compose logs crawl4ai --tail=20

# Quick healthcheck
curl http://localhost:5001/health
# Expected: {"status":"ok"}
```

### 5. Access the UI

Open your browser to:

```
http://YOUR_SERVER_IP:5001
```

---

## API Keys & External Services

| Service | Required? | Purpose | Free Tier |
| --- | --- | --- | --- |
| **Gemini API** | ✅ Yes | LLM extraction from web pages + auto-discovery | Free tier available at [aistudio.google.com](https://aistudio.google.com) |
| **Ticketmaster API** | ✅ Yes | Official event data with venue coordinates | Free at [developer.ticketmaster.com](https://developer.ticketmaster.com) |
| **Firecrawl API** | ⬜ Optional | Cloud fallback if Crawl4AI fails | Free tier at [firecrawl.dev](https://firecrawl.dev) |
| **Telegram Bot** | ⬜ Optional | Push notifications for confirmed events | Free — create via [@BotFather](https://t.me/BotFather) |

### Getting a Telegram Bot Token

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token → `TELEGRAM_BOT_TOKEN`
4. Send a message to your new bot, then visit:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
5. Find `chat.id` in the response → `TELEGRAM_CHAT_ID`

---

## Configuration

### Environment Variables

Secrets are stored in `.env` on the server (never committed to git):

| Variable | Default | Description |
| --- | --- | --- |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `TICKETMASTER_API_KEY` | — | Ticketmaster Discovery API key |
| `FIRECRAWL_API_KEY` | — | Firecrawl API key (optional) |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token (optional) |
| `TELEGRAM_CHAT_ID` | — | Telegram chat/channel ID (optional) |
| `CRAWL4AI_BASE_URL` | `http://crawl4ai:11235` | Crawl4AI sidecar URL (change if running separately) |
| `APP_TIMEZONE` | `America/Vancouver` | Timezone for display and scheduling |
| `SCAN_INTERVAL_HOURS` | `6` | Default hours between scans |

### Runtime Settings (UI)

These are editable from the **Settings** page in the dashboard and persist to `data/settings.json`:

| Setting | Default | Description |
| --- | --- | --- |
| `scan_interval_hours` | `6` | Hours between automated scans |
| `timezone` | `America/Vancouver` | Display timezone |
| `notify_confirmed` | `true` | Send Telegram for new confirmed events |
| `notify_review_summary` | `true` | Send Telegram summary for possible events |
| `daily_digest_enabled` | `false` | Enable daily summary notifications |
| `daily_digest_time` | `21:00` | Time for daily digest (24h format) |

---

## Docker Architecture

```yaml
services:
  tourtracker:
    build: .                      # Builds from Dockerfile (Python 3.12-slim)
    container_name: TourTracker
    ports:
      - "5001:8000"               # Access the UI at http://server:5001
    volumes:
      - ./data:/app/data          # Persistent: database, logs, settings.json
    env_file: .env                # Secrets injected here
    depends_on:
      crawl4ai:
        condition: service_healthy # Waits for Crawl4AI to be ready
    restart: unless-stopped
    healthcheck:
      test: curl -f http://localhost:8000/health
      interval: 30s
      start_period: 15s

  crawl4ai:
    image: unclecode/crawl4ai:latest
    container_name: TourTracker-Crawl4AI
    shm_size: 1g                  # Required for headless Chromium
    restart: unless-stopped
    healthcheck:
      test: curl -f http://localhost:11235/health
      interval: 30s
      start_period: 45s           # Chromium takes time to initialize
```

### Important Notes

- **Code is baked into the Docker image** via `COPY . .` in the Dockerfile. Only `./data` is volume-mounted. This means **every code change requires rebuilding** the image.
- **Single Uvicorn worker** is mandatory — APScheduler runs in-process and would duplicate jobs with multiple workers.
- **Non-root user** — the Dockerfile creates an `appuser` for security.
- **Unraid labels** are included for Unraid's Docker UI integration.

---

## Development Workflow

### Local Setup

```bash
# Clone the repo
git clone https://github.com/e-fied/artistv2.git
cd artistv2

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env with your API keys
cp .env.example .env
nano .env

# Run locally (without Docker)
uvicorn main:app --reload --port 8000
```

### Deploy → Test Cycle

Because the application runs on an Unraid server via Docker, every code change follows this workflow:

#### Step 1: Push changes from your local machine

```bash
cd /Users/ef/Developer/artistv2
git add -A
git commit -m "descriptive commit message"
git push origin main
```

#### Step 2: SSH into the server, pull, and rebuild

```bash
ssh root@<UNRAID_IP> "cd /mnt/user/appdata/artistv2 && git pull origin main && docker compose up --build -d"
```

#### Step 3: Verify

```bash
ssh root@<UNRAID_IP> "cd /mnt/user/appdata/artistv2 && docker compose logs tourtracker --tail=30"
```

#### One-liner (push + deploy + verify)

```bash
cd /Users/ef/Developer/artistv2 && \
git add -A && git commit -m "your message" && git push origin main && \
ssh root@<UNRAID_IP> "cd /mnt/user/appdata/artistv2 && git pull origin main && docker compose up --build -d && sleep 15 && curl -s http://localhost:5001/health"
```

#### When to use which Docker command

| What changed | Command |
| --- | --- |
| Python code, templates, CSS, requirements | `docker compose up --build -d` |
| `docker-compose.yml` itself | `docker compose down && docker compose up --build -d` |
| Just need to restart the app (no code change) | `docker compose restart tourtracker` |
| Crawl4AI issues | `docker compose restart crawl4ai` |

### Running Tests

```bash
cd /Users/ef/Developer/artistv2
source .venv/bin/activate
python -m pytest tests/ -v
```

Currently tested:
- `test_dedup.py` — dedup key generation, normalization, collision handling
- `test_location_matcher.py` — haversine distance calculations, city/alias matching

---

## Key Design Decisions

| Decision | Rationale |
| --- | --- |
| **SQLite with WAL mode** | Set via PRAGMA on every connection. Prevents `database is locked` under concurrent reads/writes from the scheduler + web UI. No need for PostgreSQL at this scale. |
| **Single Uvicorn worker** | APScheduler runs in-process; multiple workers would spawn duplicate schedulers and run scans simultaneously. |
| **Dedup key = SHA-256(artist\|name\|venue\|city\|date)** | First 32 chars of hash. Deterministic, idempotent. Does not include time (intentional — most artists don't do two shows at the same venue on the same day). |
| **Status never downgrades** | Once `confirmed`, an event stays confirmed even if a lower-confidence source re-discovers it. Priority: `rejected(0) < expired(1) < possible(2) < confirmed(3)`. |
| **Crawl4AI as Docker sidecar** | Headless Chromium needs `shm_size: 1g`. Running it in a separate container keeps the main app image small and lets them restart independently. |
| **Gemini structured output** | `response_mime_type="application/json"` + `response_schema=ExtractionResult` guarantees parseable responses. No regex parsing of LLM output. |
| **Settings layering** | Secrets in `.env` (never persisted to disk), runtime preferences in `data/settings.json` (editable from UI). Clean separation. |
| **Firecrawl as fallback** | Some sites block headless Chrome. Firecrawl uses a different approach and often succeeds where Crawl4AI fails. The crawler tries both automatically. |
| **No Alembic (yet)** | Tables are auto-created on startup via `Base.metadata.create_all()`. Adding/changing columns on existing tables requires manual migration. |

---

## Known Limitations & Gotchas

- Some artist pages render a tour shell plus location-aware banner text like `NO SHOWS NEARBY` or `REQUEST A SHOW`, while the actual events are loaded later from an embedded API. In those cases, inspect the page source or Scan Debug output for vendor hints such as `initEvents(...)`, `eventPortalToken`, `locationId`, `eventsDataReady`, Seated widget ids, or Punchup API references.
- For supported vendors, prefer fetching the underlying event API over trying to make Crawl4AI click more UI. The repo already includes fallbacks for Seated, Punchup, and Upnex / LeadConnector event portals.

1. **Crawl4AI response format is inconsistent** — the `markdown` field can be a string OR a dict with `fit_markdown`/`raw` keys. The crawler service handles both (see `crawler.py`).

2. **Gemini `response.parsed` can be `None`** — even on a 200 response, if the schema doesn't match the output. Always null-check.

3. **No automatic schema migrations** — if you add/rename columns on existing tables, the SQLite DB won't update. You'll need to either drop and recreate the DB or run manual ALTER TABLE statements.

4. **Template access pattern** — templates are on `request.app.state.templates`, not imported directly. Routes must use `request.app.state.templates.TemplateResponse(...)`.

5. **The `data/` directory is git-ignored** — the database, logs, and settings.json are never committed. They persist only on the server via the Docker volume mount.

6. **Dedup does not include event time** — two events at the same venue on the same date but different times will collide. This is intentional for the current use case.

7. **Long SQLite transactions** — despite WAL mode, holding transactions open across HTTP calls or sleep periods can cause locking. The scanner commits frequently.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `database is locked` | Verify single worker: `--workers 1` in Dockerfile CMD. Check WAL: `sqlite3 data/tourtracker.db "PRAGMA journal_mode;"` should return `wal`. |
| Templates not updating after deploy | Code is `COPY`'d into the image. You must `docker compose up --build -d` (not just `restart`). |
| Crawl4AI healthcheck failing | Takes 30-45s to start. Check: `docker compose logs crawl4ai --tail=20`. Ensure `shm_size: 1g` is set. |
| Port 5001 not responding | Run `docker compose ps`. The `tourtracker` container waits for `crawl4ai` to be healthy. |
| `ModuleNotFoundError` | Added a dependency to `requirements.txt`? Must rebuild with `--build`. |
| Permissions error on `/app/data` | Run on host: `chmod -R 777 /mnt/user/appdata/artistv2/data` |
| Gemini extraction returns nothing | Check API key is valid. Check `docker compose logs tourtracker` for error details. Gemini may rate-limit. |
| Telegram notifications not sending | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. Send a test message to your bot first. |
| Scan runs but finds 0 events | Verify the artist has at least one source (Ticketmaster or URL). Check the Scan History page for per-source errors. |

---

## License

Private repository. All rights reserved.
