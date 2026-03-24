"""
Carrefour UAE scraper
Targets: https://www.carrefouruae.com
Strategy: Carrefour uses a Salesforce Commerce Cloud / React storefront.
          Product listings are fetched via their internal search API (OCAPI / custom REST).
"""

import asyncio
import aiohttp
import logging
from datetime import date
from typing import Optional
from .base import BaseScraper, ScrapedPrice

logger = logging.getLogger(__name__)

CARREFOUR_SEARCH_URL = "https://api.carrefouruae.com/api/v7/search"
CARREFOUR_PRODUCT_URL = "https://www.carrefouruae.com/mafuae/en/search?keyword={keyword}"

# Fallback: direct HTML scraper via playwright if API is blocked
CARREFOUR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-AE,en;q=0.9,ar;q=0.8",
    "Referer": "https://www.carrefouruae.com/",
    "x-api-key": "",  # set via env CARREFOUR_API_KEY if obtained
    "storeId": "mafuae",
    "lang": "en",
}

class CarrefourScraper(BaseScraper):
    store_name = "Carrefour"

    def __init__(self, session: aiohttp.ClientSession):
        super().__init__(session)

    async def search_product(self, keyword: str) -> Optional[ScrapedPrice]:
        """
        Search Carrefour for a product keyword and return the best-matching price.
        Tries the internal search API first, then falls back to HTML parsing.
        """
        # --- Strategy 1: Internal JSON API ---
        try:
            params = {
                "query": keyword,
                "lang": "en",
                "currentPage": 0,
                "pageSize": 5,
                "sortBy": "relevance",
                "storeId": "mafuae",
            }
            async with self.session.get(
                CARREFOUR_SEARCH_URL,
                params=params,
                headers=CARREFOUR_HEADERS,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    products = data.get("products", [])
                    if products:
                        best = products[0]
                        price = self._extract_price(best)
                        if price:
                            return ScrapedPrice(
                                store=self.store_name,
                                product_name=best.get("name", keyword),
                                search_keyword=keyword,
                                price=price,
                                unit=best.get("unit", ""),
                                url=f"https://www.carrefouruae.com/mafuae/en/p/{best.get('code','')}",
                                scraped_date=date.today().isoformat(),
                                currency="AED",
                                in_stock=best.get("stock", {}).get("stockLevelStatus") != "outOfStock",
                            )
        except Exception as e:
            logger.warning(f"[Carrefour] API strategy failed for '{keyword}': {e}")

        # --- Strategy 2: HTML scraping via playwright (see playwright_scraper.py) ---
        logger.info(f"[Carrefour] Falling back to HTML scraper for '{keyword}'")
        return await self._html_fallback(keyword)

    def _extract_price(self, product: dict) -> Optional[float]:
        """Extract price from Carrefour product JSON."""
        try:
            price_info = product.get("price", {})
            # Try promotional price first, then regular
            for key in ("specialPrice", "offerPrice", "value", "formattedValue"):
                val = price_info.get(key)
                if val:
                    return float(str(val).replace(",", "").replace("AED", "").strip())
        except Exception:
            pass
        return None

    async def _html_fallback(self, keyword: str) -> Optional[ScrapedPrice]:
        """
        HTML fallback: fetch the search results page and parse with BeautifulSoup.
        Carrefour renders prices in: <span class="css-lvv38i">AED XX.XX</span>
        """
        try:
            url = CARREFOUR_PRODUCT_URL.format(keyword=keyword.replace(" ", "+"))
            async with self.session.get(
                url,
                headers=CARREFOUR_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    return self._parse_html(html, keyword, url)
        except Exception as e:
            logger.error(f"[Carrefour] HTML fallback failed for '{keyword}': {e}")
        return None

    def _parse_html(self, html: str, keyword: str, url: str) -> Optional[ScrapedPrice]:
        """Parse Carrefour HTML search results page."""
        from bs4 import BeautifulSoup
        import re
        soup = BeautifulSoup(html, "lxml")

        # Carrefour price selectors (update if site changes)
        price_selectors = [
            "span.css-lvv38i",
            "[data-testid='product-price']",
            ".product-price",
            "span[class*='Price']",
        ]
        product_name_selectors = [
            "h2[class*='product-name']",
            "[data-testid='product-name']",
            "h2.css-1i90gmp",
        ]

        price = None
        product_name = keyword

        for sel in price_selectors:
            el = soup.select_one(sel)
            if el:
                raw = el.get_text(strip=True)
                match = re.search(r"[\d,]+\.?\d*", raw.replace(",", ""))
                if match:
                    try:
                        price = float(match.group())
                        break
                    except ValueError:
                        continue

        for sel in product_name_selectors:
            el = soup.select_one(sel)
            if el:
                product_name = el.get_text(strip=True)
                break

        if price:
            return ScrapedPrice(
                store=self.store_name,
                product_name=product_name,
                search_keyword=keyword,
                price=price,
                unit="",
                url=url,
                scraped_date=date.today().isoformat(),
                currency="AED",
                in_stock=True,
            )
        return None
