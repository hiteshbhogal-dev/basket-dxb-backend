"""
Scheduler — runs the scraper every day at 06:00 Dubai time (UTC+4).
Uses APScheduler. Can also be triggered manually via CLI or API.

Run standalone: python -m scheduler.run_scraper
Run with web API: uvicorn api.server:app (scheduler starts automatically)
"""

import asyncio
import logging
import time
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scraper import scrape_all, ALL_KEYWORDS
from db.database import save_prices, log_scrape_run, init_db

logger = logging.getLogger(__name__)


async def run_full_scrape(keywords: list = None):
    """
    Full scrape run: scrape all stores → save to DB → log result.
    Called by the scheduler every morning and optionally via the API.
    """
    keywords = keywords or ALL_KEYWORDS
    logger.info(f"[Scheduler] Starting scrape run — {len(keywords)} keywords, {date.today()}")
    start = time.time()

    try:
        results = await scrape_all(keywords)
    except Exception as e:
        logger.error(f"[Scheduler] Scrape run crashed: {e}")
        results = []

    duration = time.time() - start
    saved = await save_prices(results)

    # Log per-store stats
    store_results = {}
    for r in results:
        store_results.setdefault(r.store, []).append(r)

    for store, items in store_results.items():
        await log_scrape_run(
            store=store,
            total=len(keywords),
            success=len(items),
            failed=len(keywords) - len(items),
            duration=duration,
        )

    logger.info(
        f"[Scheduler] Run complete in {duration:.1f}s — "
        f"{saved} prices saved from {len(results)} raw results"
    )
    return results


def start_scheduler():
    """Start the APScheduler cron job. Call this once at app startup."""
    init_db()
    scheduler = AsyncIOScheduler(timezone="Asia/Dubai")
    scheduler.add_job(
        run_full_scrape,
        trigger=CronTrigger(hour=6, minute=0, timezone="Asia/Dubai"),
        id="daily_scrape",
        name="Daily grocery price scrape",
        replace_existing=True,
        misfire_grace_time=3600,  # run even if missed by up to 1 hour
    )
    scheduler.start()
    logger.info("[Scheduler] Daily scrape scheduled for 06:00 Asia/Dubai")
    return scheduler


if __name__ == "__main__":
    # Run once immediately from CLI
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info("Running manual scrape from CLI...")
    asyncio.run(run_full_scrape())
