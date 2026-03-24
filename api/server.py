"""
Basket DXB — FastAPI REST API
Serves scraped price data to the frontend HTML app.

Run:  uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
Docs: http://localhost:8000/docs
"""

import logging
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from db.database import (
    init_db,
    get_latest_prices,
    get_price_history,
    get_cheapest_store_summary,
    get_price_movers,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Basket DXB API",
    description="Real-time grocery price tracker for Dubai supermarkets.",
    version="1.0.0",
)

# Allow the frontend HTML file to call this API from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    init_db()
    logger.info("Basket DXB API started. DB initialised.")


# ─────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────

@app.get("/", tags=["health"])
def root():
    return {"status": "ok", "service": "Basket DXB API", "date": date.today().isoformat()}


@app.get("/health", tags=["health"])
def health():
    return {"status": "healthy"}


@app.get("/api/prices", tags=["prices"])
async def get_prices(keyword: Optional[str] = Query(None, description="Filter by search keyword")):
    """
    Return latest prices for all products (or a specific keyword).
    Groups results by keyword: { keyword: { LuLu: price, Carrefour: price, ... } }
    """
    rows = await get_latest_prices(keyword)
    if not rows:
        return {"data": {}, "count": 0}

    grouped: dict = {}
    for row in rows:
        kw = row["keyword"]
        if kw not in grouped:
            grouped[kw] = {
                "keyword": kw,
                "product_name": row["product_name"],
                "unit": row["unit"],
                "stores": {},
                "best_store": None,
                "best_price": None,
                "scraped_date": row["scraped_date"],
            }
        grouped[kw]["stores"][row["store"]] = {
            "price": row["price"],
            "url": row["url"],
            "in_stock": bool(row["in_stock"]),
        }

    # Annotate cheapest store
    for kw, item in grouped.items():
        if item["stores"]:
            best = min(item["stores"].items(), key=lambda x: x[1]["price"])
            item["best_store"] = best[0]
            item["best_price"] = best[1]["price"]

    return {"data": grouped, "count": len(grouped), "as_of": date.today().isoformat()}


@app.get("/api/prices/{keyword:path}", tags=["prices"])
async def get_price_for_keyword(keyword: str):
    """Return prices for a single keyword across all stores."""
    rows = await get_latest_prices(keyword)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No prices found for '{keyword}'")
    return {"keyword": keyword, "prices": rows}


@app.get("/api/history/{keyword:path}", tags=["history"])
async def price_history(
    keyword: str,
    days: int = Query(7, ge=1, le=30, description="Number of days of history"),
):
    """Return N-day price history for a keyword."""
    rows = await get_price_history(keyword, days=days)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No history for '{keyword}'")

    # Restructure into { date: { store: price } }
    by_date: dict = {}
    for row in rows:
        d = row["scraped_date"]
        if d not in by_date:
            by_date[d] = {}
        by_date[d][row["store"]] = row["price"]

    return {
        "keyword": keyword,
        "days": days,
        "history": by_date,
        "raw": rows,
    }


@app.get("/api/summary", tags=["summary"])
async def store_summary(days: int = Query(3, ge=1, le=30)):
    """
    Return which store was cheapest most often in the last N days,
    and average basket cost per store.
    """
    data = await get_cheapest_store_summary(days=days)
    return data


@app.get("/api/movers", tags=["summary"])
async def price_movers():
    """Return products with the biggest price changes since yesterday."""
    rows = await get_price_movers()
    drops = [r for r in rows if r["change"] < 0]
    rises = [r for r in rows if r["change"] > 0]
    return {
        "drops": sorted(drops, key=lambda x: x["change"]),
        "rises": sorted(rises, key=lambda x: x["change"], reverse=True),
        "as_of": date.today().isoformat(),
    }


@app.post("/api/scrape/trigger", tags=["admin"])
async def trigger_scrape(background_tasks: BackgroundTasks, keywords: Optional[list[str]] = None):
    """
    Manually trigger a scrape run (runs in background).
    Requires the scraper to be installed in the same environment.
    """
    from scheduler.run_scraper import run_full_scrape
    background_tasks.add_task(run_full_scrape, keywords)
    return {"status": "scrape triggered", "message": "Running in background. Check /api/scrape/status for progress."}


@app.get("/api/scrape/status", tags=["admin"])
async def scrape_status():
    """Return the last 10 scrape run logs."""
    from db.database import DB_PATH
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM scrape_log ORDER BY created_at DESC LIMIT 10"
        )
        rows = [dict(r) for r in await cur.fetchall()]
    return {"runs": rows}


@app.get("/api/search", tags=["prices"])
async def search_prices(q: str = Query(..., min_length=2)):
    """Full-text search across all keyword prices."""
    all_rows = await get_latest_prices()
    matched = [r for r in all_rows if q.lower() in r["keyword"].lower()
               or (r["product_name"] and q.lower() in r["product_name"].lower())]
    return {"query": q, "results": matched, "count": len(matched)}
