import logging
import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

load_dotenv()

# Logging setup
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE  = os.getenv("LOG_FILE", "logs/basket_dxb.log")
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def start_api():
    from db.database import init_db
    init_db()

    from api.server import app
    from scheduler.run_scraper import start_scheduler

    @app.on_event("startup")
    async def _start_scheduler():
        start_scheduler()

    # IMPORTANT: Render requires dynamic port
    port = int(os.environ.get("PORT", 8000))

    logger.info(f"Starting API on port {port}")
    uvicorn.run("api.server:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    start_api()