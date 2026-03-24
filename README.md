# Basket DXB — Backend Scraper & API

Real-time grocery price tracker for Dubai supermarkets.
Scrapes **Carrefour**, **LuLu**, **Noon**, and **Spinneys** every morning at 06:00 Dubai time, stores prices in SQLite, and serves them via a REST API to the frontend.

---

## Architecture

```
basket-dxb-scraper/
├── scraper/
│   ├── __init__.py          # Orchestrator — runs all 4 scrapers concurrently
│   ├── base.py              # BaseScraper class + ScrapedPrice dataclass
│   ├── carrefour.py         # Carrefour UAE scraper
│   ├── lulu.py              # LuLu Hypermarket scraper
│   ├── noon.py              # Noon grocery scraper
│   ├── spinneys.py          # Spinneys scraper (uses Algolia)
│   └── playwright_scraper.py  # Headless browser fallback
├── api/
│   └── server.py            # FastAPI REST API
├── db/
│   └── database.py          # SQLite async database layer
├── scheduler/
│   └── run_scraper.py       # APScheduler daily job
├── logs/                    # Auto-created log files
├── main.py                  # Main entrypoint
├── requirements.txt
└── .env.example
```

### How scraping works

Each store scraper tries **two strategies** in order:

1. **JSON API** — replicates the exact REST calls the store's React frontend makes (fastest, most reliable)
2. **HTML fallback** — parses the rendered HTML with BeautifulSoup (slower, works when API is blocked)
3. **Playwright fallback** — headless Chromium for heavily JS-rendered pages (slowest, most robust)

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/yourname/basket-dxb-scraper
cd basket-dxb-scraper

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Install Playwright browser (for JS fallback scraping)
playwright install chromium
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env if needed (defaults work fine to start)
```

### 3. Run a test scrape

```bash
python main.py --scrape-now
```

This runs one full scrape across all 4 stores and saves results to `db/basket_dxb.db`.

### 4. Start the API + scheduler

```bash
python main.py
```

Opens the REST API at **http://localhost:8000** and schedules daily scraping at 06:00 Dubai time.

Interactive API docs: **http://localhost:8000/docs**

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/prices` | All latest prices grouped by keyword |
| GET | `/api/prices/{keyword}` | Prices for one keyword across all stores |
| GET | `/api/history/{keyword}?days=7` | N-day price history |
| GET | `/api/summary?days=3` | Store rankings & avg basket cost |
| GET | `/api/movers` | Biggest price changes since yesterday |
| GET | `/api/search?q=milk` | Search products by name |
| POST | `/api/scrape/trigger` | Manually trigger a scrape |
| GET | `/api/scrape/status` | Last 10 scrape run logs |

### Example response — `/api/prices?keyword=basmati rice 5kg`

```json
{
  "data": {
    "basmati rice 5kg": {
      "keyword": "basmati rice 5kg",
      "product_name": "Daawat Basmati Rice 5kg",
      "unit": "5kg",
      "stores": {
        "LuLu":      { "price": 38.50, "url": "https://...", "in_stock": true },
        "Noon":      { "price": 40.00, "url": "https://...", "in_stock": true },
        "Carrefour": { "price": 42.00, "url": "https://...", "in_stock": true },
        "Spinneys":  { "price": 48.00, "url": "https://...", "in_stock": true }
      },
      "best_store": "LuLu",
      "best_price": 38.50,
      "scraped_date": "2026-03-23"
    }
  },
  "count": 1,
  "as_of": "2026-03-23"
}
```

---

## Connecting the Frontend

In `basket-dxb-v2.html`, replace the hardcoded `HOUSEHOLDS` data with live API calls:

```javascript
const API_BASE = "http://localhost:8000";  // or your server URL

async function loadLivePrices() {
  const res = await fetch(`${API_BASE}/api/prices`);
  const { data } = await res.json();
  // data is a map of keyword → { stores: {LuLu: price, ...}, best_store, ... }
  return data;
}

async function loadSummary() {
  const res = await fetch(`${API_BASE}/api/summary?days=3`);
  return res.json();
}

async function loadMovers() {
  const res = await fetch(`${API_BASE}/api/movers`);
  return res.json();
}
```

---

## Deploying to a VPS (Ubuntu)

### Install & run as a systemd service

```bash
# 1. Upload project to /opt/basket-dxb
scp -r basket-dxb-scraper user@yourserver:/opt/basket-dxb

# 2. Install dependencies
cd /opt/basket-dxb && pip install -r requirements.txt && playwright install chromium

# 3. Create systemd service
sudo nano /etc/systemd/system/basket-dxb.service
```

```ini
[Unit]
Description=Basket DXB Price Scraper & API
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/basket-dxb
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable basket-dxb
sudo systemctl start basket-dxb
sudo systemctl status basket-dxb
```

### Nginx reverse proxy (optional)

```nginx
server {
    listen 80;
    server_name api.basketdxb.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Important Notes on Scraping

1. **Rate limiting** — All scrapers include random delays (1.5–4s) between requests. Do not lower these.
2. **Legal** — Always check a site's `robots.txt` and Terms of Service before scraping. For production, consider reaching out to stores for an official data feed or API partnership.
3. **Selector drift** — Websites update their HTML regularly. When a scraper returns no results, inspect the site's network tab and update the selectors in the relevant scraper file.
4. **IP bans** — If scrapers get blocked, consider rotating residential proxies via services like BrightData or Oxylabs. Add proxy support via `aiohttp`'s `proxy` parameter.
5. **Playwright** — The headless browser fallback is slower (5–10s/request) but more robust. Enable it in `.env` with `USE_PLAYWRIGHT=true`.

---

## License

MIT — for personal and educational use. Always respect store ToS.
