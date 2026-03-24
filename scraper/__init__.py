"""
Scraper orchestrator — runs all four store scrapers concurrently
with rate limiting, retries, and error isolation.
"""

import asyncio
import aiohttp
import logging
from typing import Dict, List

from .base import ScrapedPrice
from .carrefour import CarrefourScraper
from .lulu import LuluScraper
from .noon import NoonScraper
from .spinneys import SpinneyScraper

logger = logging.getLogger(__name__)

# Max concurrent requests across ALL scrapers combined
GLOBAL_CONCURRENCY = 4

# Items to track — covers all household types
ALL_KEYWORDS = [
    # Rice & Grains
    "basmati rice 5kg", "jasmine rice 5kg", "ponni rice", "idli rice", "brown rice",
    "bulgur wheat", "freekeh", "quinoa", "risotto arborio rice", "vermicelli",
    # Lentils & Pulses
    "toor dal", "moong dal", "chana dal", "masoor dal red lentils", "urad dal",
    "kabuli chana chickpeas", "rajma kidney beans", "brown lentils", "fava beans",
    "black eyed peas",
    # Spices
    "cumin seeds jeera", "turmeric powder", "coriander powder", "red chilli powder",
    "garam masala", "cardamom pods", "mustard seeds", "fenugreek seeds methi",
    "asafoetida hing", "baharat spice", "za'atar", "saffron",
    # Vegetables
    "tomatoes 1kg", "onions 1kg", "potatoes 1kg", "ginger 250g", "garlic",
    "green chilli", "okra bhindi", "eggplant brinjal", "spinach",
    "cucumber", "zucchini courgette", "bitter gourd karela",
    "broccoli", "mushrooms", "bell peppers", "carrots", "asparagus",
    # Dairy
    "full cream milk 1L", "eggs 12 pack", "butter 250g", "Greek yoghurt",
    "paneer 400g", "ghee 500g", "labneh", "cheddar cheese", "mozzarella",
    "cream cheese", "laban drinking yoghurt",
    # Meat & Fish
    "chicken breast 1kg", "minced beef 500g", "mutton 1kg", "salmon fillet",
    "lamb chops", "pork belly", "shrimp prawns 500g", "tuna canned",
    # Bread & Flour
    "atta wheat flour 5kg", "maida all purpose flour", "besan gram flour",
    "sourdough loaf", "brown bread sliced", "pita bread", "khubz arabic bread",
    # Oils & Condiments
    "sunflower oil 2L", "olive oil 500ml", "mustard oil", "tahini",
    "soy sauce", "fish sauce", "tomato ketchup",
    # Beverages
    "chai masala tea", "PG Tips tea bags", "orange juice 1L", "coconut water",
    "milo", "nescafe coffee", "qahwa arabic coffee",
    # Snacks & Sweets
    "dates medjool 500g", "dark chocolate", "mixed nuts 200g", "digestive biscuits",
    # Fresh Herbs
    "fresh basil", "fresh parsley", "lemongrass", "pandan leaves",
]


async def scrape_all(keywords: List[str] = None) -> List[ScrapedPrice]:
    """
    Run all four scrapers concurrently for the given keywords.
    Returns a flat list of ScrapedPrice objects.
    """
    if keywords is None:
        keywords = ALL_KEYWORDS

    semaphore = asyncio.Semaphore(GLOBAL_CONCURRENCY)
    all_results: List[ScrapedPrice] = []

    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
    timeout = aiohttp.ClientTimeout(total=30, connect=5)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        scrapers = [
            CarrefourScraper(session),
            LuluScraper(session),
            NoonScraper(session),
            SpinneyScraper(session),
        ]

        async def scrape_one(scraper, keyword: str):
            async with semaphore:
                try:
                    result = await scraper.search_product(keyword)
                    if result:
                        return result
                except Exception as e:
                    logger.error(f"[{scraper.store_name}] Unhandled error for '{keyword}': {e}")
            return None

        tasks = [
            scrape_one(scraper, kw)
            for scraper in scrapers
            for kw in keywords
        ]

        logger.info(f"Starting {len(tasks)} scrape tasks ({len(scrapers)} stores × {len(keywords)} keywords)")
        raw = await asyncio.gather(*tasks, return_exceptions=True)

        for item in raw:
            if isinstance(item, ScrapedPrice):
                all_results.append(item)
            elif isinstance(item, Exception):
                logger.warning(f"Task raised exception: {item}")

    logger.info(f"Scraping complete. {len(all_results)}/{len(tasks)} results collected.")
    return all_results


def run_scraper(keywords: List[str] = None) -> List[ScrapedPrice]:
    """Synchronous entry point for use from scheduler or CLI."""
    return asyncio.run(scrape_all(keywords))
