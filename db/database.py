"""
Database layer — SQLite via aiosqlite for async writes.
Schema:
  prices       — one row per (store, keyword, date)
  products     — canonical product name + keyword mapping
  scrape_log   — audit log of every scrape run
"""

import aiosqlite
import sqlite3
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "db" / "basket_dxb.db"


def init_db():
    """Create tables if they don't exist. Run once at startup."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS prices (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            store          TEXT    NOT NULL,
            keyword        TEXT    NOT NULL,
            product_name   TEXT,
            price          REAL    NOT NULL,
            unit           TEXT,
            url            TEXT,
            in_stock       INTEGER DEFAULT 1,
            currency       TEXT    DEFAULT 'AED',
            scraped_date   TEXT    NOT NULL,
            created_at     TEXT    DEFAULT (datetime('now')),
            UNIQUE(store, keyword, scraped_date)
        );

        CREATE INDEX IF NOT EXISTS idx_prices_keyword      ON prices(keyword);
        CREATE INDEX IF NOT EXISTS idx_prices_date         ON prices(scraped_date);
        CREATE INDEX IF NOT EXISTS idx_prices_store        ON prices(store);
        CREATE INDEX IF NOT EXISTS idx_prices_store_kw_dt  ON prices(store, keyword, scraped_date);

        CREATE TABLE IF NOT EXISTS scrape_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date     TEXT    NOT NULL,
            store        TEXT,
            total_items  INTEGER DEFAULT 0,
            success      INTEGER DEFAULT 0,
            failed       INTEGER DEFAULT 0,
            duration_s   REAL,
            created_at   TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS keyword_aliases (
            keyword      TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            category     TEXT,
            household    TEXT
        );
    """)
    conn.commit()
    conn.close()
    logger.info(f"Database initialised at {DB_PATH}")


async def save_prices(results: list) -> int:
    """Upsert a list of ScrapedPrice objects. Returns count saved."""
    saved = 0
    async with aiosqlite.connect(DB_PATH) as db:
        for r in results:
            try:
                await db.execute(
                    """
                    INSERT INTO prices (store, keyword, product_name, price, unit, url, in_stock, currency, scraped_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, keyword, scraped_date) DO UPDATE SET
                        price        = excluded.price,
                        product_name = excluded.product_name,
                        unit         = excluded.unit,
                        url          = excluded.url,
                        in_stock     = excluded.in_stock
                    """,
                    (r.store, r.search_keyword, r.product_name, r.price,
                     r.unit, r.url, int(r.in_stock), r.currency, r.scraped_date),
                )
                saved += 1
            except Exception as e:
                logger.error(f"DB save error for {r.store}/{r.search_keyword}: {e}")
        await db.commit()
    return saved


async def get_latest_prices(keyword: str = None) -> list[dict]:
    """Return the most recent price for each (store, keyword) pair."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if keyword:
            cur = await db.execute(
                """
                SELECT p.store, p.keyword, p.product_name, p.price, p.unit, p.url,
                       p.in_stock, p.scraped_date
                FROM prices p
                INNER JOIN (
                    SELECT store, keyword, MAX(scraped_date) AS max_date
                    FROM prices
                    WHERE keyword = ?
                    GROUP BY store, keyword
                ) latest ON p.store = latest.store AND p.keyword = latest.keyword
                         AND p.scraped_date = latest.max_date
                ORDER BY p.price ASC
                """,
                (keyword,),
            )
        else:
            cur = await db.execute(
                """
                SELECT p.store, p.keyword, p.product_name, p.price, p.unit, p.url,
                       p.in_stock, p.scraped_date
                FROM prices p
                INNER JOIN (
                    SELECT store, keyword, MAX(scraped_date) AS max_date
                    FROM prices
                    GROUP BY store, keyword
                ) latest ON p.store = latest.store AND p.keyword = latest.keyword
                         AND p.scraped_date = latest.max_date
                ORDER BY p.keyword, p.price ASC
                """
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_price_history(keyword: str, days: int = 7) -> list[dict]:
    """Return price history for a keyword for the last N days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT store, keyword, product_name, price, scraped_date
            FROM prices
            WHERE keyword = ? AND scraped_date >= ?
            ORDER BY scraped_date ASC, price ASC
            """,
            (keyword, since),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_cheapest_store_summary(days: int = 3) -> dict:
    """
    Returns which store was cheapest most often in the last N days,
    and average basket cost per store.
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Average price per store
        cur = await db.execute(
            """
            SELECT store, AVG(price) as avg_price, COUNT(DISTINCT keyword) as item_count
            FROM prices
            WHERE scraped_date >= ?
            GROUP BY store
            ORDER BY avg_price ASC
            """,
            (since,),
        )
        store_avgs = [dict(r) for r in await cur.fetchall()]

        # Count how many times each store was cheapest per keyword
        cur = await db.execute(
            """
            WITH ranked AS (
                SELECT store, keyword, price, scraped_date,
                       RANK() OVER (PARTITION BY keyword, scraped_date ORDER BY price ASC) as rnk
                FROM prices
                WHERE scraped_date >= ?
            )
            SELECT store, COUNT(*) as cheapest_count
            FROM ranked
            WHERE rnk = 1
            GROUP BY store
            ORDER BY cheapest_count DESC
            """,
            (since,),
        )
        cheapest_counts = [dict(r) for r in await cur.fetchall()]

        return {
            "store_averages": store_avgs,
            "cheapest_counts": cheapest_counts,
            "period_days": days,
        }


async def get_price_movers(since_date: str = None) -> list[dict]:
    """
    Returns items with the biggest price changes between yesterday and today.
    """
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    since_date = since_date or yesterday

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT t.store, t.keyword, t.product_name,
                   t.price as today_price, y.price as yesterday_price,
                   ROUND(t.price - y.price, 2) as change,
                   ROUND((t.price - y.price) / y.price * 100, 1) as pct_change
            FROM prices t
            JOIN prices y ON t.store = y.store AND t.keyword = y.keyword
            WHERE t.scraped_date = ? AND y.scraped_date = ?
              AND t.price != y.price
            ORDER BY ABS(t.price - y.price) DESC
            LIMIT 20
            """,
            (today, since_date),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def log_scrape_run(store: str, total: int, success: int, failed: int, duration: float):
    """Write a scrape run record to the audit log."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO scrape_log (run_date, store, total_items, success, failed, duration_s) VALUES (?,?,?,?,?,?)",
            (date.today().isoformat(), store, total, success, failed, round(duration, 2)),
        )
        await db.commit()
