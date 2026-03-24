"""
Playwright scraper — used as a last resort for stores that heavily
rely on JavaScript rendering and block aiohttp requests.

Install: pip install playwright && playwright install chromium
"""

import asyncio
import logging
import re
from datetime import date
from typing import Optional
from .base import ScrapedPrice

logger = logging.getLogger(__name__)


async def scrape_with_playwright(
    store_name: str,
    url: str,
    keyword: str,
    price_selector: str,
    name_selector: str,
) -> Optional[ScrapedPrice]:
    """
    Generic Playwright scraper. Opens a headless Chromium browser,
    navigates to `url`, waits for `price_selector` to appear, then extracts data.
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ]
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-AE",
                timezone_id="Asia/Dubai",
                viewport={"width": 1366, "height": 768},
            )

            # Block images/fonts/media to speed up scraping
            await ctx.route(
                "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,webm}",
                lambda route: route.abort()
            )

            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_selector(price_selector, timeout=8000)

                price_text = await page.text_content(price_selector)
                name_text  = await page.text_content(name_selector) if name_selector else keyword

                price = None
                if price_text:
                    match = re.search(r"[\d]+\.?\d*", price_text.replace(",", ""))
                    if match:
                        price = float(match.group())

                if price:
                    return ScrapedPrice(
                        store=store_name,
                        product_name=(name_text or keyword).strip(),
                        search_keyword=keyword,
                        price=price,
                        unit="",
                        url=url,
                        scraped_date=date.today().isoformat(),
                        currency="AED",
                        in_stock=True,
                    )
            except PlaywrightTimeout:
                logger.warning(f"[Playwright/{store_name}] Timeout waiting for '{price_selector}' on {url}")
            finally:
                await page.close()
            await browser.close()

    except ImportError:
        logger.error("[Playwright] playwright not installed. Run: pip install playwright && playwright install chromium")
    except Exception as e:
        logger.error(f"[Playwright/{store_name}] Error scraping {url}: {e}")

    return None


# Store-specific Playwright configs
PLAYWRIGHT_CONFIGS = {
    "Carrefour": {
        "url_template": "https://www.carrefouruae.com/mafuae/en/search?keyword={keyword}",
        "price_selector": "span[class*='css-lvv38i'], [data-testid='product-price']",
        "name_selector": "h2[class*='product-name'], [data-testid='product-name']",
    },
    "LuLu": {
        "url_template": "https://www.luluhypermarket.com/en-ae/search?q={keyword}",
        "price_selector": ".price-tag, [class*='selling-price']",
        "name_selector": ".product-title, h2.product-name",
    },
    "Noon": {
        "url_template": "https://www.noon.com/uae-en/search/?q={keyword}&c=grocery",
        "price_selector": "strong.amount, [data-qa='product-price']",
        "name_selector": "[data-qa='product-name']",
    },
    "Spinneys": {
        "url_template": "https://www.spinneys.com/en-ae/search?q={keyword}",
        "price_selector": ".price, [class*='Price']",
        "name_selector": "h2[class*='name'], .product-name",
    },
}


async def playwright_scrape_store(store: str, keyword: str) -> Optional[ScrapedPrice]:
    """Convenience wrapper for store-specific Playwright scraping."""
    config = PLAYWRIGHT_CONFIGS.get(store)
    if not config:
        logger.error(f"[Playwright] No config for store: {store}")
        return None
    url = config["url_template"].format(keyword=keyword.replace(" ", "+"))
    return await scrape_with_playwright(
        store_name=store,
        url=url,
        keyword=keyword,
        price_selector=config["price_selector"],
        name_selector=config["name_selector"],
    )
