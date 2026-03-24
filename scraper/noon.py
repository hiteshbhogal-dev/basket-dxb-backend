"""
Noon UAE grocery scraper
Targets: https://www.noon.com/uae-en/grocery/
Strategy: Noon exposes a public search API used by their React frontend.
          We replicate the same calls the browser makes.
"""

import aiohttp
import logging
import re
from datetime import date
from typing import Optional
from .base import BaseScraper, ScrapedPrice

logger = logging.getLogger(__name__)

NOON_SEARCH_URL = "https://www.noon.com/uae-en/search/?q={keyword}&c=grocery"
NOON_API_URL    = "https://noon-catalog-api.noon.com/v3/catalog/search"

NOON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, */*",
    "Accept-Language": "en-AE,en;q=0.9",
    "Origin": "https://www.noon.com",
    "Referer": "https://www.noon.com/",
    "x-platform": "web",
    "x-country-code": "AE",
    "x-currency-code": "AED",
    "x-locale": "en-ae",
}

class NoonScraper(BaseScraper):
    store_name = "Noon"

    def __init__(self, session: aiohttp.ClientSession):
        super().__init__(session)

    async def search_product(self, keyword: str) -> Optional[ScrapedPrice]:
        # --- Strategy 1: Noon catalog API ---
        try:
            payload = {
                "query": keyword,
                "filters": {"category": ["grocery"]},
                "sort": {"by": "popularity", "dir": "desc"},
                "limit": 5,
                "offset": 0,
                "lang": "en",
                "country": "AE",
                "currency": "AED",
            }
            async with self.session.post(
                NOON_API_URL,
                json=payload,
                headers=NOON_HEADERS,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    hits = (
                        data.get("hits", [])
                        or data.get("results", {}).get("hits", [])
                        or data.get("data", {}).get("products", [])
                    )
                    if hits:
                        best = hits[0]
                        price = self._extract_price(best)
                        if price:
                            sku = best.get("sku", best.get("id", ""))
                            return ScrapedPrice(
                                store=self.store_name,
                                product_name=best.get("name", keyword),
                                search_keyword=keyword,
                                price=price,
                                unit=best.get("unitDescription", ""),
                                url=f"https://www.noon.com/uae-en/{sku}/p/",
                                scraped_date=date.today().isoformat(),
                                currency="AED",
                                in_stock=best.get("inStock", True),
                            )
        except Exception as e:
            logger.warning(f"[Noon] API strategy failed for '{keyword}': {e}")

        # --- Strategy 2: HTML fallback ---
        return await self._html_fallback(keyword)

    def _extract_price(self, product: dict) -> Optional[float]:
        """Extract price from Noon product JSON."""
        # Noon often nests price under 'price' or 'offer'
        for key in ("salePrice", "offerPrice", "price", "basePrice"):
            val = product.get(key)
            if val is not None:
                try:
                    return float(str(val).replace(",", ""))
                except Exception:
                    pass
        price_obj = product.get("price", {})
        if isinstance(price_obj, dict):
            for key in ("salePrice", "value", "selling"):
                val = price_obj.get(key)
                if val:
                    cleaned = re.sub(r"[^\d.]", "", str(val))
                    try:
                        return float(cleaned)
                    except Exception:
                        pass
        return None

    async def _html_fallback(self, keyword: str) -> Optional[ScrapedPrice]:
        url = NOON_SEARCH_URL.format(keyword=keyword.replace(" ", "+"))
        try:
            async with self.session.get(
                url,
                headers=NOON_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    return self._parse_html(html, keyword, url)
        except Exception as e:
            logger.error(f"[Noon] HTML fallback failed for '{keyword}': {e}")
        return None

    def _parse_html(self, html: str, keyword: str, url: str) -> Optional[ScrapedPrice]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        price_selectors = [
            "strong.amount",
            "[class*='priceNow']",
            "[data-qa='product-price']",
            ".sc-eCImPb",
            "span[class*='price']",
        ]
        name_selectors = [
            "[data-qa='product-name']",
            "h2[class*='name']",
            ".sc-jHcCik",
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

        for sel in name_selectors:
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
