"""
Base scraper class — all store scrapers inherit from this.
"""

import asyncio
import aiohttp
import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScrapedPrice:
    store: str
    product_name: str
    search_keyword: str
    price: float
    unit: str
    url: str
    scraped_date: str
    currency: str = "AED"
    in_stock: bool = True
    raw_data: dict = field(default_factory=dict)


class BaseScraper:
    store_name: str = "Unknown"

    # Politeness delays (seconds) — randomised to look more human
    MIN_DELAY = 1.5
    MAX_DELAY = 4.0

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def search_product(self, keyword: str) -> Optional[ScrapedPrice]:
        raise NotImplementedError

    async def _polite_delay(self):
        """Random delay between requests to avoid rate limiting."""
        delay = random.uniform(self.MIN_DELAY, self.MAX_DELAY)
        await asyncio.sleep(delay)

    async def scrape_keywords(self, keywords: list[str]) -> list[ScrapedPrice]:
        """Scrape a list of keywords with polite delays."""
        results = []
        for kw in keywords:
            await self._polite_delay()
            result = await self.search_product(kw)
            if result:
                results.append(result)
        return results
