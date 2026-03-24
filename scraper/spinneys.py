"""
Spinneys UAE scraper
Targets: https://www.spinneys.com/en-ae/
Strategy: Spinneys uses Algolia search under the hood. We replicate the
          exact Algolia API call the browser makes.
"""

import aiohttp
import logging
import re
from datetime import date
from typing import Optional
from .base import BaseScraper, ScrapedPrice

logger = logging.getLogger(__name__)

# Algolia config — extracted from Spinneys network tab (public, rotates rarely)
SPINNEYS_ALGOLIA_URL  = "https://rqq0hhkbbd-dsn.algolia.net/1/indexes/*/queries"
SPINNEYS_ALGOLIA_APP  = "RQQ0HHKBBD"
SPINNEYS_ALGOLIA_KEY  = "d0d298aa7c24a02c39c1a7d69d682bb2"  # public search-only key
SPINNEYS_INDEX        = "prod_spinneys_uae_products_en"

SPINNEYS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "x-algolia-application-id": SPINNEYS_ALGOLIA_APP,
    "x-algolia-api-key": SPINNEYS_ALGOLIA_KEY,
}

SPINNEYS_HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-AE,en;q=0.9",
}

class SpinneyScraper(BaseScraper):
    store_name = "Spinneys"

    def __init__(self, session: aiohttp.ClientSession):
        super().__init__(session)

    async def search_product(self, keyword: str) -> Optional[ScrapedPrice]:
        # --- Strategy 1: Algolia search API ---
        try:
            payload = {
                "requests": [{
                    "indexName": SPINNEYS_INDEX,
                    "params": f"query={keyword}&hitsPerPage=5&filters=inStock%3Atrue"
                }]
            }
            async with self.session.post(
                SPINNEYS_ALGOLIA_URL,
                json=payload,
                headers=SPINNEYS_HEADERS,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [{}])
                    hits = results[0].get("hits", []) if results else []
                    if hits:
                        best = hits[0]
                        price = self._extract_price(best)
                        if price:
                            return ScrapedPrice(
                                store=self.store_name,
                                product_name=best.get("name", best.get("title", keyword)),
                                search_keyword=keyword,
                                price=price,
                                unit=best.get("unit_of_measure", best.get("unitOfMeasure", "")),
                                url=f"https://www.spinneys.com/en-ae/{best.get('url_key', best.get('slug', ''))}",
                                scraped_date=date.today().isoformat(),
                                currency="AED",
                                in_stock=best.get("inStock", True),
                            )
        except Exception as e:
            logger.warning(f"[Spinneys] Algolia strategy failed for '{keyword}': {e}")

        # --- Strategy 2: HTML fallback ---
        return await self._html_fallback(keyword)

    def _extract_price(self, hit: dict) -> Optional[float]:
        """Extract price from Algolia hit."""
        for key in ("price_aed", "special_price", "price", "finalPrice", "selling_price"):
            val = hit.get(key)
            if val is not None and str(val).replace(".", "").isdigit():
                try:
                    return float(val)
                except Exception:
                    pass
        # Nested price map
        price_map = hit.get("price", {})
        if isinstance(price_map, dict):
            aed = price_map.get("AED", price_map.get("aed", {}))
            if isinstance(aed, dict):
                val = aed.get("default", aed.get("special"))
                if val:
                    try:
                        return float(val)
                    except Exception:
                        pass
        return None

    async def _html_fallback(self, keyword: str) -> Optional[ScrapedPrice]:
        url = f"https://www.spinneys.com/en-ae/search?q={keyword.replace(' ', '+')}"
        try:
            async with self.session.get(
                url,
                headers=SPINNEYS_HTML_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    return self._parse_html(html, keyword, url)
        except Exception as e:
            logger.error(f"[Spinneys] HTML fallback failed for '{keyword}': {e}")
        return None

    def _parse_html(self, html: str, keyword: str, url: str) -> Optional[ScrapedPrice]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        price_selectors = [
            ".price", "span[class*='price']", "[data-testid='price']",
            ".product-price", "[class*='Price']",
        ]
        price = None
        product_name = keyword
        for sel in price_selectors:
            el = soup.select_one(sel)
            if el:
                raw = el.get_text(strip=True)
                match = re.search(r"[\d]+\.?\d*", raw.replace(",", ""))
                if match:
                    try:
                        price = float(match.group())
                        break
                    except ValueError:
                        continue
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
