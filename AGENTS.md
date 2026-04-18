# AGENTS.md — Tour Tracker v2

> **Purpose:** This file exists to give AI coding agents (Codex, Copilot, Gemini, Claude, etc.) full context about the application, its architecture, conventions, and — critically — the deployment/testing workflow that must be followed after every code change.

---

## 1. Project Overview

**Tour Tracker v2** is an automated, AI-powered background scraping agent and web dashboard that discovers, extracts, and tracks comedy and music artist tour dates. It monitors Ticketmaster, official artist websites, and manually-added URLs for new events near user-configured locations, then sends Telegram notifications for confirmed matches.

**Repository:** `https://github.com/e-fied/artistv2.git`
**Production host:** Unraid server (Docker Compose deployment)
**Access URL:** `http://nas.local:5001`

### Current State / Recent Context (April 2026)

The app has recently been tuned for debugging crawl failures and dynamic tour pages. A new Codex chat should assume these features exist unless the code says otherwise:

- **Seated widget fallback is implemented.** Adam Ray's site exposed tour dates through `https://cdn.seated.com/api/tour/{uuid}?include=tour-events`. `CrawlerService` now detects Seated widget/Nuxt references, resolves the artist/tour id, fetches the Seated JSON:API endpoint, and appends those events to the crawl markdown before Gemini extraction.
- **Punchup API fallback is implemented.** Timmy No Brakes' Punchup tour page (`https://punchup.live/timmynobrakes/tour`) rendered mostly as a Next.js shell to crawlers, while the actual dates came from `https://punchup.live/api/shows?comedianId={uuid}&startDatetime={iso}`. `CrawlerService` now detects Punchup pages, resolves the comedian id from embedded Next.js/RSC data, fetches the Punchup shows API, filters out shows hidden from that comedian page, and appends full tour events to the crawl markdown before Gemini extraction.
- **Embedded event enrichers are isolated.** JSON-LD, Seated, and Punchup enrichment run independently, so one failing adapter should not prevent another adapter from appending events.
- **Crawler diagnostics are implemented.** If a page crawls successfully but no events are extracted, the crawler diagnoses likely causes such as very little page text, bot blocking, blank pages, JSON-LD-only events, or dates rendered after load.
- **Opt-in scan debug artifacts are implemented.** Settings → Scan Debugging can capture prompts, Gemini raw/parsed responses, cleaned crawl samples, Ticketmaster candidates, and processed events to `data/debug/scan_{scan_run_id}.json`.
- **Scan History shows live progress.** Running scans update a progress message such as "checking Ticketmaster", "crawling URL", or "sending cleaned chars to Gemini", and the Scan History table auto-refreshes while scans are running.
- **Source Health can link to debug artifacts.** Failing sources show `Latest Debug` when a debug artifact exists for their latest scan result. If none exists, enable Scan Debugging and force retry.
- **Source Health Telegram alerts are implemented.** Settings → Notifications has `Notify on source health problems`; when enabled, crawler/API warnings are sent to Telegram with artist, source type, URL, notice count, and warning text.
- **Timezone display is Vancouver-local.** Templates use the `localtime` Jinja filter from `main.py`; stored DB timestamps are UTC-ish/naive, displayed in `America/Vancouver` by default.
- **Location lat/lon can be inferred for known cities.** Location forms can geocode common city names/fallback known cities such as Denver, so the user does not have to manually know latitude/longitude.
- **Sidebar links use trailing slashes.** Routes mounted at prefixes like `/scans`, `/locations`, `/logs`, `/settings` define `@router.get("/")`; nav links should use `/scans/`, `/locations/`, `/logs/`, `/settings/` to avoid HTMX boosted redirect weirdness.
- **Recent relevant commits:** `d46fa72 Isolate embedded event enrichment adapters`, `a4e50e8 Add Punchup tour API fallback`, `c1716ec Notify source health problems`, `22d73f6 Fix settings save and scan progress`, `a71f6b0 Add opt-in scan debug artifacts`, `b62d0f8 Improve scan debugging and location entry`, `a4bc5e6 Add crawler diagnostics for empty tour pages`, `aaaf1a6 Add Seated widget tour fallback`.

---

## 2. Tech Stack

| Layer              | Technology                                                                 |
| ------------------ | -------------------------------------------------------------------------- |
| **Language**       | Python 3.12                                                                |
| **Web framework**  | FastAPI (ASGI, Uvicorn, single worker)                                     |
| **Templating**     | Jinja2 (server-rendered HTML)                                              |
| **Frontend**       | Vanilla CSS, Alpine.js, HTMX — no build step, no bundler                  |
| **Database**       | SQLite (WAL mode) via SQLAlchemy 2.x (mapped columns, DeclarativeBase)     |
| **Scheduler**      | APScheduler (BackgroundScheduler, SQLAlchemy job store, interval triggers)  |
| **LLM**            | Google Gemini 2.5 Flash (structured JSON output via `google-genai` SDK)    |
| **Web scraping**   | Crawl4AI (self-hosted Docker sidecar) + Firecrawl (cloud API fallback)     |
| **Event API**      | Ticketmaster Discovery API                                                 |
| **Notifications**  | Telegram Bot API (HTML-formatted messages)                                 |
| **Containerization** | Docker + Docker Compose (two services: `tourtracker` + `crawl4ai`)       |

---

## 3. Directory Structure

```
artistv2/
├── main.py                     # FastAPI app factory, lifespan, router registration
├── Dockerfile                  # Python 3.12-slim, non-root user, port 8000
├── docker-compose.yml          # Two services: tourtracker (port 5001→8000) + crawl4ai sidecar
├── requirements.txt            # Pinned Python dependencies
├── .env.example                # Template for secrets (never committed)
├── .gitignore
│
├── app/
│   ├── __init__.py
│   ├── config.py               # AppSettings (Pydantic), load/save from env + settings.json
│   ├── database.py             # SQLAlchemy engine (SQLite WAL), SessionLocal, get_db()
│   ├── scheduler.py            # APScheduler setup, start/stop, scan interval job
│   ├── seed.py                 # Seed data (Vancouver/Lower Mainland + aliases)
│   │
│   ├── models/                 # SQLAlchemy ORM models (DeclarativeBase, mapped_column)
│   │   ├── __init__.py         # Re-exports all models
│   │   ├── artist.py           # Artist, ArtistSource, ArtistLocation
│   │   ├── event.py            # Event, EventReview
│   │   ├── location.py         # LocationProfile, LocationAlias
│   │   ├── scan.py             # ScanRun, ScanSourceResult
│   │   └── settings.py         # AppSetting (KV store in DB)
│   │
│   ├── schemas/                # Pydantic schemas (NOT ORM models)
│   │   ├── __init__.py
│   │   └── gemini.py           # ExtractedEvent, ExtractionResult — Gemini structured output schema
│   │
│   ├── services/               # Business logic (no HTTP/routing concerns)
│   │   ├── __init__.py
│   │   ├── scanner.py          # Main scan orchestrator: scan_all_artists(), _scan_single_artist()
│   │   ├── crawler.py          # CrawlerService: Crawl4AI → Firecrawl fallback, markdown cleaning
│   │   ├── debug_capture.py    # Opt-in JSON scan debug artifacts under data/debug/
│   │   ├── extractor.py        # ExtractorService: Gemini structured extraction from markdown
│   │   ├── autofind.py         # Auto-discover official tour page via Gemini + Google Search grounding
│   │   ├── dedup.py            # make_dedup_key(), upsert_event() — SHA-256 based deduplication
│   │   ├── location_matcher.py # Haversine geo-matching, city/alias matching, confidence scoring
│   │   ├── ticketmaster.py     # TicketmasterClient: attraction + keyword search, event parsing
│   │   └── notifier.py         # Telegram send + message formatting (confirmed events, review summary)
│   │
│   ├── routes/                 # FastAPI routers (thin controllers, delegate to services)
│   │   ├── __init__.py
│   │   ├── dashboard.py        # GET / — main dashboard
│   │   ├── artists.py          # CRUD for artists, TM search, auto-find
│   │   ├── events.py           # Event listing, filtering, status updates
│   │   ├── locations.py        # Location profile CRUD + alias management
│   │   ├── settings_routes.py  # Settings view/update UI
│   │   ├── scans.py            # Scan history, manual trigger
│   │   ├── sources.py          # Artist source management
│   │   ├── logs.py             # Real-time log tailing endpoint
│   │   └── health.py           # GET /health — container healthcheck
│   │
│   ├── templates/              # Jinja2 HTML templates
│   │   ├── base.html           # Base layout (nav, CSS, Alpine/HTMX includes)
│   │   ├── dashboard.html
│   │   ├── artists/            # Artist list, detail, TM search, add/edit forms
│   │   ├── events/             # Event list, detail
│   │   ├── locations/          # Location management UI
│   │   ├── settings/           # Settings page
│   │   ├── scans/              # Scan history
│   │   ├── sources/            # Source management
│   │   ├── logs/               # Log viewer
│   │   └── review/             # Event review inbox
│   │
│   └── static/
│       └── css/                # Vanilla CSS stylesheets
│
├── data/                       # Runtime data (git-ignored, Docker volume-mounted)
│   ├── tourtracker.db          # SQLite database
│   ├── settings.json           # Non-secret settings persisted from UI
│   ├── debug/                  # Opt-in scan debug artifacts (git-ignored)
│   └── logs/
│       └── app.log             # Application log file
│
└── tests/
    ├── test_crawler_punchup.py # Punchup API fallback/id parsing tests
    ├── test_dedup.py           # Dedup key generation tests
    └── test_location_matcher.py # Haversine + matching tests
```

---

## 4. Application Architecture & Data Flow

### 4.1 Scan Pipeline (Core Business Logic)

```
APScheduler (every N hours)
  └─▶ scanner.scan_all_artists()
       ├─▶ For each active (non-paused) Artist:
       │    ├─▶ [Ticketmaster Source]
       │    │    └─ TicketmasterClient.search_events_by_attraction() or search_by_keyword()
       │    │         └─ Returns structured event dicts
       │    │
       │    ├─▶ [Web Sources] (official_website, manual_url)
       │    │    ├─ CrawlerService.fetch_markdown() → tries Crawl4AI sidecar, falls back to Firecrawl
       │    │    ├─ CrawlerService optionally enriches markdown with JSON-LD/Event data, Seated widget API events, and Punchup shows API events
       │    │    ├─ CrawlerService.clean_markdown() → strip boilerplate, cap at 50k chars
       │    │    └─ ExtractorService.extract_events() → Gemini 2.5 Flash structured JSON output
       │    │
       │    └─▶ _process_event() for each discovered event:
       │         ├─ location_matcher.match_event_to_locations()
       │         │   └─ Priority: exact_city (1.0) → alias (0.95) → haversine radius (0.7–1.0)
       │         ├─ dedup.upsert_event()
       │         │   └─ SHA-256 key: artist_id|name|venue|city|date
       │         │   └─ Never downgrades status (confirmed stays confirmed)
       │         └─ notifier.send_telegram() if new + confirmed
       │
       └─▶ Record ScanRun + ScanSourceResult history
            ├─▶ Optional debug_capture JSON artifact if Settings → Scan Debugging is enabled
            └─▶ Optional Telegram source-health alert if a source warning/error occurs
```

### 4.2 Key Design Decisions

- **SQLite WAL mode** — Set via PRAGMA on every connection to prevent `database is locked` under concurrent reads/writes from the scheduler + web UI.
- **Single Uvicorn worker** — Required because APScheduler runs in-process; multiple workers would spawn duplicate schedulers.
- **Dedup key hashing** — Uses first 32 chars of SHA-256(artist_id|name|venue|city|date) to prevent duplicate event rows.
- **Status never downgrades** — Once an event is `confirmed`, it stays confirmed even if a lower-confidence source re-discovers it.
- **Crawl4AI sidecar** — Runs as a separate Docker container with shared memory (`shm_size: 1g`) for headless Chromium. The main app communicates with it over HTTP (`http://crawl4ai:11235`).
- **Gemini structured output** — Uses `response_mime_type="application/json"` + `response_schema=ExtractionResult` for guaranteed parseable responses.
- **Settings layering** — Secrets come from `.env` (env vars), non-secret preferences are persisted to `data/settings.json` from the UI.
- **Debug artifacts are file-based, not DB rows** — `app/services/debug_capture.py` writes `data/debug/scan_{id}.json`; it scrubs obvious API key fields and truncates giant strings.
- **Source warnings are not necessarily fatal** — A source can have `fetch_success=True` but still carry a diagnostic in `fetch_error` when the page crawled but produced no events or very little usable text.

### 4.3 Database Models (ERD Summary)

```
Artist (1) ──▶ (N) ArtistSource        (ticketmaster, official_website, manual_url)
Artist (1) ──▶ (N) ArtistLocation      (links to LocationProfile, home vs travel)
Artist (1) ──▶ (N) Event               (discovered events)
Artist (1) ──▶ (N) ScanRun             (scan history)

Event (1) ──▶ (N) EventReview          (user confirm/reject actions)

LocationProfile (1) ──▶ (N) LocationAlias   (e.g. "Burnaby" is alias of "Vancouver")

ScanRun (1) ──▶ (N) ScanSourceResult    (per-source results within a scan)
```

### 4.4 Configuration & Environment Variables

**Secrets (`.env` only, never in settings.json):**
- `TICKETMASTER_API_KEY`
- `GEMINI_API_KEY`
- `FIRECRAWL_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

**Optional overrides:**
- `CRAWL4AI_BASE_URL` — defaults to `http://crawl4ai:11235` (Docker internal)
- `APP_TIMEZONE` — defaults to `America/Vancouver`
- `SCAN_INTERVAL_HOURS` — defaults to `6`

**Runtime settings (UI-editable, saved to `data/settings.json`):**
- `scan_interval_hours`
- `timezone`
- `crawl4ai_base_url`
- `notify_confirmed`
- `notify_review_summary`
- `notify_source_health`
- `daily_digest_enabled`
- `daily_digest_time`
- `debug_scan_capture`
- `debug_scan_retention`

### 4.5 Scan Debugging Workflow

Use this workflow when the user asks "what did Crawl4AI return?", "why did Source Health warn?", or "why did Gemini miss dates?":

1. Go to Settings and enable **Capture scan debug artifacts**.
2. Force retry the artist/source from Source Health or run Check Now from the dashboard.
3. Open Scan History and click **Debug** for the scan, or Source Health → **Latest Debug** for the source.
4. Inspect:
   - `Cleaned Crawl Sample`: what was actually sent toward Gemini after cleaning/enrichment.
   - `LLM Request`: model, prompt, temperature, input character count.
   - `LLM Raw Response`: raw Gemini response text.
   - `LLM Parsed Response`: structured schema parse.
   - `Events Found`: raw event data plus `process_result` such as `confirmed`, `possible`, `existing`, or `no_match`.
   - Ticketmaster debug: attraction/keyword mode, searched profiles, returned candidates, and process results.
5. Turn debug capture off after testing so `data/debug` does not grow unnecessarily. Retention is controlled by `debug_scan_retention`.

Common source warning text:

`Crawler returned very little page text. The page may be blank, blocked, or rendering tour dates after load.`

This means the crawler received too little useful page text for trustworthy extraction. It can be caused by JavaScript-rendered dates after load, bot-blocking, cookie/geo gates, or a site that uses an embedded API. For Seated widgets, check whether the fallback found and appended events from `cdn.seated.com/api/tour/...`. For Punchup pages, check whether the fallback found a comedian id and appended events from `punchup.live/api/shows`.

### 4.6 Telegram Notification Types

Telegram currently supports:

- Confirmed event notifications via `format_event_notification()`.
- Review summaries for possible matches via `format_review_summary()`.
- Source health warnings via `format_source_health_alert()`.

Source health alerts require:

- `settings.notify_source_health == True`
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` configured in `.env`
- A source warning/error during scan, such as Ticketmaster failure, crawler failure, Gemini extraction failure, or crawler diagnostics for no extracted events.

---

## 5. Coding Conventions

### 5.1 Python Style
- **Python 3.12** — use `from __future__ import annotations` at the top of every module.
- **Type hints everywhere** — use `Mapped[T]` + `mapped_column()` for SQLAlchemy models.
- **Pydantic v2** — `BaseModel`, `model_dump()` (not `.dict()`), `Field()` with descriptions.
- **Logging** — use `logging.getLogger(__name__)` in each module. Log to both file (`data/logs/app.log`) and stderr.
- **Imports** — group by stdlib → third-party → local (`app.*`). Use `noqa: E402` for deferred imports after mount/config.

### 5.2 FastAPI Patterns
- **Routers** — each file in `app/routes/` defines a `router = APIRouter(...)`. Registered in `main.py`.
- **Database dependency** — use `db: Session = Depends(get_db)` for request-scoped sessions.
- **Templates** — accessed via `request.app.state.templates` (set in `main.py`).
- **HTMX partials** — some routes return HTML fragments for HTMX swap targets (no full page reload).

### 5.3 Frontend Patterns
- **No build step** — all CSS/JS is served from `/static/`. No npm, no Tailwind, no bundler.
- **Alpine.js** — used for client-side interactivity (dropdowns, toggles, modals).
- **HTMX** — used for partial page updates (form submissions, live search, log tailing).
- **Jinja2 template inheritance** — all pages extend `base.html`.
- **Trailing-slash routes matter** — When a router has `prefix="/settings"` plus `@router.get("/")`, links/forms should use `/settings/`, not `/settings`. This is especially important because `<body hx-boost="true">` can make redirect behavior feel like a dead click.
- **Avoid nested forms** — A prior bug made Settings "Save" appear broken because the Telegram test button used a `<form>` inside the main settings `<form>`. Use button `formaction`/`formmethod` or move forms apart.

### 5.4 Testing
- Tests live in `tests/`.
- Preferred local test command:
  ```bash
  APP_DATA_DIR=/tmp/artist-data-test PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q
  ```
- Current test coverage: deduplication logic, location matching (haversine, aliases).
- Route smoke test with lifespan startup:
  ```bash
  APP_DATA_DIR=/tmp/artist-data-test DATABASE_URL=sqlite:////tmp/artist-data-test/app.db PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "from fastapi.testclient import TestClient; from main import app; c=TestClient(app); c.__enter__(); paths=['/health','/','/settings/','/sources/health','/scans/','/locations/','/logs/']; [print(p, c.get(p).status_code) for p in paths]; c.__exit__(None, None, None)"
  ```
- Do **not** use local `/app/data` during tests. Set `APP_DATA_DIR` to `/tmp/...` or another writable location.

---

## 6. ⚠️ CRITICAL: Deployment & Testing Workflow

> **This is the most important section.** Every code change must follow this exact workflow to be tested in production.

### 6.1 Development Environment

- **Local machine:** macOS (`/Users/ef/Developer/artistv2`)
- **Production server:** Unraid NAS (Docker host)
- **Deployment path on Unraid:** `/mnt/user/appdata/artistv2`
- **Connection:** SSH from local machine into Unraid

### 6.2 The Workflow: Git Push → SSH → Docker Restart

**After EVERY code change, you MUST follow this sequence:**

#### Step 1: Commit & push from local machine

```bash
cd /Users/ef/Developer/artistv2
git add -A
git commit -m "descriptive commit message"
git push origin main
```

> ⚠️ **Always push to `origin main` after every update.** The Unraid server pulls from this remote. If you don't push, the server won't have your changes.

#### Step 2: SSH into the Unraid server

```bash
ssh root@<UNRAID_IP>
```

> Replace `<UNRAID_IP>` with the actual Unraid server IP address on the local network.

#### Step 3: Pull the latest code on the server

```bash
cd /mnt/user/appdata/artistv2
git pull origin main
```

#### Step 4: Rebuild and restart the Docker container(s)

**If you changed Python code, templates, CSS, or requirements:**
```bash
docker compose up --build -d
```

**If you ONLY changed templates or static files (no Python/dependency changes):**
```bash
# The source is volume-mounted for data, but code is baked into the image.
# You still need to rebuild:
docker compose up --build -d
```

**If you changed the Crawl4AI configuration or need to restart only the sidecar:**
```bash
docker compose restart crawl4ai
```

**If you need to restart only the main app (no rebuild):**
```bash
docker compose restart tourtracker
```

**If you changed `docker-compose.yml` itself:**
```bash
docker compose down
docker compose up --build -d
```

#### Step 5: Verify the deployment

```bash
# Check container status
docker compose ps

# Check logs for errors
docker compose logs tourtracker --tail=50
docker compose logs crawl4ai --tail=20

# Quick healthcheck
curl http://localhost:5001/health
```

#### Step 6: Exit SSH

```bash
exit
```

### 6.3 Quick Reference (Copy-Paste Block)

**Full deploy from local terminal after making changes:**

```bash
# 1. Push changes
cd /Users/ef/Developer/artistv2
git add -A && git commit -m "your message" && git push origin main

# 2. SSH in, pull, rebuild
ssh root@<UNRAID_IP> "cd /mnt/user/appdata/artistv2 && git pull origin main && docker compose up --build -d"
```

> The one-liner above combines steps 2–4 into a single SSH command. You can also chain the healthcheck:
> ```bash
> ssh root@<UNRAID_IP> "cd /mnt/user/appdata/artistv2 && git pull origin main && docker compose up --build -d && sleep 15 && curl -s http://localhost:5001/health"
> ```

Known working deploy command from this Mac when using the 1Password SSH agent:

```bash
SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock" ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 root@nas.local "cd /mnt/user/appdata/artistv2 && git pull origin main && docker compose up --build -d && sleep 8 && docker compose ps && echo '--- tourtracker logs ---' && docker compose logs tourtracker --tail=80 && echo '--- health ---' && curl -sS http://localhost:5001/health"
```

### 6.4 Troubleshooting Deployment

| Symptom | Fix |
| --- | --- |
| `database is locked` | Ensure single Uvicorn worker (already configured). Check WAL mode: `sqlite3 /mnt/user/appdata/artistv2/data/tourtracker.db "PRAGMA journal_mode;"` should return `wal`. |
| Templates not updating | Code is copied into the Docker image at build time (`COPY . .`), so you **must** `docker compose up --build -d`. A plain `restart` won't pick up file changes. |
| Crawl4AI healthcheck failing | The sidecar takes ~30-45s to start (Chromium load). Wait and check: `docker compose logs crawl4ai --tail=20`. |
| Port 5001 not responding | Check `docker compose ps`. The `tourtracker` container depends on `crawl4ai` being healthy first. |
| `ModuleNotFoundError` | You probably added a dependency to `requirements.txt` but didn't `--build`. Always rebuild after dependency changes. |
| Permissions error on `/app/data` | The Dockerfile creates `/app/data` with `chmod 777`. If the volume mount overrides this, run: `chmod -R 777 /mnt/user/appdata/artistv2/data` on the Unraid host. |

---

## 7. Docker Architecture

### 7.1 Services

```yaml
services:
  tourtracker:          # Main FastAPI app
    build: .            # Builds from local Dockerfile
    container_name: TourTracker
    ports: "5001:8000"  # External:Internal
    volumes:
      - ./data:/app/data   # Persistent data (DB, logs, settings)
    env_file: .env
    depends_on:
      crawl4ai:
        condition: service_healthy
    healthcheck: curl http://localhost:8000/health

  crawl4ai:             # Headless browser for web scraping
    image: unclecode/crawl4ai:latest
    container_name: TourTracker-Crawl4AI
    shm_size: 1g        # Required for Chromium
    healthcheck: curl http://localhost:11235/health
```

### 7.2 Important Notes for Agents

- **Code is baked into the image** — `COPY . .` in the Dockerfile means the app code lives inside the container, NOT in a volume mount. Only `./data` is mounted. This means **every code change requires a rebuild** (`docker compose up --build -d`).
- **The `.env` file lives on the Unraid server** at `/mnt/user/appdata/artistv2/.env`. It is git-ignored. If you add new env vars, document them in `.env.example` and remind the user to update `.env` on the server.
- **Never run with multiple Uvicorn workers.** The APScheduler runs in-process and would duplicate if multiple workers existed.

---

## 8. Common Tasks for Agents

### Adding a new API route
1. Create or edit a file in `app/routes/`.
2. Define a `router = APIRouter(prefix="/...", tags=["..."])`.
3. Register it in `main.py` with `app.include_router(router)`.
4. If it needs a template, add it under `app/templates/<section>/`.

### Adding a new database model
1. Add the model class in `app/models/` (use `mapped_column`, `Mapped[T]`).
2. Re-export it from `app/models/__init__.py`.
3. Tables are auto-created on startup via `Base.metadata.create_all()`.
4. ⚠️ For schema changes on an existing table, you'll need Alembic (not yet configured) or a manual migration.

### Adding a new environment variable
1. Add it to `app/config.py` in the `AppSettings` model.
2. Add the `os.getenv()` call in `_settings_from_env()`.
3. Add it to `.env.example` with a comment.
4. **Remind the user** to update `.env` on the Unraid server.

### Adding a new service
1. Create a new file in `app/services/`.
2. Keep services stateless where possible — accept `settings` and `db` as arguments.
3. Use `SessionLocal()` for background tasks (not request-scoped `get_db()`).

### Running tests locally
```bash
cd /Users/ef/Developer/artistv2
source .venv/bin/activate
python -m pytest tests/ -v
```

---

## 9. Known Gotchas & Pitfalls

1. **Crawl4AI response format is inconsistent** — The `markdown` field can be a string OR a dict with `fit_markdown`/`raw` keys. The crawler service handles both cases (`crawler.py` lines 85-93). Always check the type.

2. **Dynamic tour pages may need embedded API fallbacks** — Crawl4AI may see a shell page while dates arrive later via XHR/widget JS. Before assuming Gemini failed, inspect Scan Debug and page scripts/network clues. Seated and Punchup are currently handled by dedicated fallbacks; other vendors may need similar adapters.

3. **"See All" buttons often hide already-fetched data** — Some artist pages initially render only a handful of shows and require clicking labels such as "See All (84)" in the browser. For Punchup, the full show list already comes from `/api/shows`; the button is client-side display logic, so the API fallback is more reliable than trying to make Crawl4AI click it. For new vendors, inspect the network/API data before adding click automation.

4. **Very little page text warning** — This is a crawler/content warning, not just an LLM miss. It means there was not enough text to confidently extract events. Check `Cleaned Crawl Sample` in Scan Debug and consider direct API/widget fallbacks.

5. **SQLite concurrency** — Despite WAL mode, long-running transactions can still cause issues. The scanner opens its own `SessionLocal()` and commits frequently. Don't hold transactions open across HTTP calls or sleep periods.

6. **Gemini structured output** — The `response.parsed` attribute may be `None` even on a 200 response if the schema doesn't match. Always null-check. `ExtractorService.last_debug` captures prompt/model/raw/parsed data for debug artifacts.

7. **Template access** — Templates are on `request.app.state.templates`, NOT imported directly. Routes must accept `request: Request` and use `request.app.state.templates.TemplateResponse(...)`.

8. **No Alembic yet** — Schema migrations are not automated. If you add/change columns, the table won't update on existing databases. Either add Alembic or provide a manual SQL migration script. Prefer avoiding schema changes unless necessary; recent debug artifacts intentionally use JSON files to avoid migration needs.

9. **Dedup key does not include time** — Two events at the same venue on the same date but different times will collide. This is intentional (most artists don't do two shows at the same venue on the same day).

10. **The `data/` directory is git-ignored** — The database, logs, settings.json, and debug artifacts are never committed. They persist on the Unraid server via the Docker volume mount.

11. **Settings booleans default false in forms** — FastAPI checkbox fields use `Form(False)`. If adding a new checkbox, add it to `AppSettings`, `settings_routes.update_settings()`, and `settings/index.html`.

12. **Source health notices increment on diagnostics** — `consecutive_failures` may increment for "no events / suspicious crawl" diagnostics, even when HTTP fetching technically succeeded. Source Health is meant to expose these as attention items.

13. **HTMX boosted links and redirects** — Because `hx-boost` is on `<body>`, avoid relying on slash redirects for navigation or forms. Use exact route URLs.

---

## 10. Summary of Mandatory Rules

1. ✅ **Always `git push origin main` after every code change.**
2. ✅ **Always SSH into Unraid, `git pull`, and `docker compose up --build -d` to test.**
3. ✅ **Never add secrets to code or settings.json** — they go in `.env` only.
4. ✅ **Never use multiple Uvicorn workers** — APScheduler will duplicate.
5. ✅ **Always rebuild the Docker image** after code/template/dependency changes (`--build` flag).
6. ✅ **Check `docker compose logs tourtracker --tail=50`** after every deploy to verify no errors.
7. ✅ **Update `.env.example`** when adding new environment variables.
8. ✅ **Preserve all existing comments and docstrings** unless directly related to your change.
9. ✅ **Use exact trailing-slash URLs** for prefix routes such as `/settings/`, `/scans/`, `/locations/`, and `/logs/`.
10. ✅ **When debugging crawl misses, enable Scan Debugging and inspect `Latest Debug` before changing prompts.**
