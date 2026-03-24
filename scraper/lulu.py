"""
LuLu Hypermarket UAE scraper
Targets: https://www.luluhypermarket.com
Strategy: LuLu uses a custom search endpoint that returns JSON.
          Products are rendered client-side from a REST API.
"""

import asyncio
import aiohttp
import logging
import re
from datetime import date
from typing import Optional
from .base import BaseScraper, ScrapedPrice

logger = logging.getLogger(__name__)

LULU_SEARCH_URL = "https://www.luluhypermarket.com/en-ae/search"
LULU_API_URL    = "https://www.luluhypermarket.com/api/v1/search/products"

LULU_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-AE,en;q=0.9",
    "Referer": "https://www.luluhypermarket.com/",
    "X-Requested-With": "XMLHttpRequest",
}

class LuluScraper(BaseScraper):
    store_name = "LuLu"

    def __init__(self, session: aiohttp.ClientSession):
        super().__init__(session)

    async def search_product(self, keyword: str) -> Optional[ScrapedPrice]:
        # --- Strategy 1: JSON API ---
        try:
            params = {
                "q": keyword,
                "lang": "en",
                "curr": "AED",
                "page": 1,
                "pageSize": 5,
            }
            async with self.session.get(
                LULU_API_URL,
                params=params,
                headers=LULU_HEADERS,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    products = (
                        data.get("data", {}).get("products", [])
                        or data.get("products", [])
                        or data.get("results", [])
                    )
                    if products:
                        best = products[0]
                        price = self._extract_price(best)
                        if price:
                            return ScrapedPrice(
                                store=self.store_name,
                                product_name=best.get("name", keyword),
                                search_keyword=keyword,
                                price=price,
                                unit=best.get("unitOfMeasure", best.get("unit", "")),
                                url=f"https://www.luluhypermarket.com{best.get('url', '')}",
                                scraped_date=date.today().isoformat(),
                                currency="AED",
                                in_stock=best.get("available", True),
                            )
        except Exception as e:
            logger.warning(f"[LuLu] API strategy failed for '{keyword}': {e}")

        # --- Strategy 2: HTML scraping ---
        return await self._html_fallback(keyword)

    def _extract_price(self, product: dict) -> Optional[float]:
        """Extract price from LuLu product JSON — tries multiple known keys."""
        for key in ("promoPrice", "offerPrice", "salePrice", "price", "sellingPrice"):
            val = product.get(key)
            if val and str(val).replace(".", "").isdigit():
                try:
                    return float(val)
                except Exception:
                    pass

        # Nested price object
        price_obj = product.get("priceData", product.get("priceInfo", {}))
        if price_obj:
            for key in ("formattedValue", "value", "price"):
                val = price_obj.get(key)
                if val:
                    cleaned = re.sub(r"[^\d.]", "", str(val))
                    try:
                        return float(cleaned)
                    except Exception:
                        pass
        return None

    async def _html_fallback(self, keyword: str) -> Optional[ScrapedPrice]:
        """HTML fallback using BeautifulSoup."""
        url = f"{LULU_SEARCH_URL}?q={keyword.replace(' ', '+')}"
        try:
            async with self.session.get(
                url,
                headers=LULU_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    return self._parse_html(html, keyword, url)
        except Exception as e:
            logger.error(f"[LuLu] HTML fallback failed for '{keyword}': {e}")
        return None

    def _parse_html(self, html: str, keyword: str, url: str) -> Optional[ScrapedPrice]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        price_selectors = [
            ".price-tag",
            "[class*='selling-price']",
            "[class*='product-price']",
            "span.price",
            ".priceTxt",
        ]
        name_selectors = [
            ".product-title",
            "h2.product-name",
            "[class*='product-name']",
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
