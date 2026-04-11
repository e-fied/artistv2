## Phase 1 & 2 Completed

The tracking and scanning systems are done.

## What's covered now: Deployment (Phase 3)

The application is completely finished and functionally robust. It is now ready to deploy identically to the `worksafedocs` container onto your Unraid server.

### Unraid Deployment Steps

1. Copy the entire `/Users/ef/Developer/artistv2` directory to your Unraid AppData share (e.g., `/mnt/user/appdata/artistv2`).
2. SSH into your Unraid server and navigate to the folder.
3. Configure your production environment variables:
   ```bash
   cp .env.example .env
   nano .env
   ```
   **Set your production API keys:**
   - `GEMINI_API_KEY` (Required for auto-finding URLs and scraping unstructured text)
   - `TICKETMASTER_API_KEY` (Required for precise TM syncing)
   - `FIRECRAWL_API_KEY` (Optional, acts as an extremely reliable fallback to Crawl4AI)
   - `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID` (Required for Telegram alerts)

4. Run the docker compose stack:
   ```bash
   docker compose up -d
   ```
5. You can access the UI on your server's IP address on port `5050` (or whichever port you exposed). The `Crawl4AI` container runs privately on port `11235` internally.

Everything will "just work" as you seeded your local database in `data/tourtracker.db` — there's no need to recreate your artists, it carries directly over!
