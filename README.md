# Tour Tracker v2

An automated, AI-powered background scraping agent and dashboard designed to discover, extract, and track comedy and artist tour dates across the web and Ticketmaster. 

## Features
- **Intelligent Web Scraping:** Uses `Crawl4AI` and large context windows to grab untamed text formatting from personal websites and blogs. 
- **AI Extraction pipeline:** Relies on Gemini (Google GenAI) to parse raw Markdown blocks into structured json schemas, ensuring we rarely miss dynamic dates format.
- **Auto-Discovery:** Automatically locates an artist's official tour page using Gemini's Google Search Grounding mechanism.
- **Idempotent Storage:** De-duplicates matches via distance proximity calculations and hashing, ensuring no repeat notifications.
- **Real-Time Log Tailing:** Tail Background processes directly in your dashboard logs UI.
- **Telegram Notifications:** Get real-time alerts when new events are officially confirmed near your tracking coordinates.

## Stack
- **Backend:** FastAPI, Python 3.12, APScheduler
- **Database:** SQLite (with advanced WAL-mode concurrency tracking to prevent db-locks) + SQLAlchemy
- **UI:** Jinja2 Templates, Vanilla CSS, Alpine.js, HTMX
- **Automation / Extractors:** Ticketmaster API, Crawl4AI, Firecrawl, Gemini 2.5 Flash

## Deployment (Docker & Unraid)

This project is fully dockerized alongside a disconnected `Crawl4AI` sidecar.

1. SSH into your host (or Unraid server).
2. Clone the repository into your storage directory:
   ```bash
   git clone https://github.com/e-fied/artistv2.git /mnt/user/appdata/artistv2
   cd /mnt/user/appdata/artistv2
   ```
3. Copy environment configuration:
   ```bash
   cp .env.example .env
   # Add your API keys: GEMINI, TICKETMASTER, FIRECRAWL, TELEGRAM
   nano .env
   ```
4. Build and deploy:
   ```bash
   docker compose up --build -d
   ```
5. Access the user interface via `http://YOUR_SERVER_IP:5001`.
