import asyncio
import logging
import re

import httpx
import trafilatura
from bs4 import BeautifulSoup

from app.core.config import Settings

logger = logging.getLogger(__name__)


class PageParser:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract_page_text(self, url: str) -> str:
        html = await self._fetch_html(url)
        if not html:
            return ""

        text = trafilatura.extract(html) or ""
        if not text.strip():
            text = self._extract_with_bs4(html)
        normalized = self._normalize_text(text)
        return normalized[: self.settings.max_page_chars]

    async def _fetch_html(self, url: str) -> str:
        headers = {"User-Agent": "MVPAnalyzerBot/1.0 (+https://example.local)"}
        max_attempts = self.settings.http_retries + 1

        for attempt in range(max_attempts):
            try:
                timeout = httpx.Timeout(self.settings.http_timeout_seconds, connect=10.0)
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.text
            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                logger.warning("Page fetch failed on attempt %s: %s", attempt + 1, exc)
                if attempt == max_attempts - 1:
                    return ""
                await asyncio.sleep(0.6 * (2**attempt))

        return ""

    @staticmethod
    def _extract_with_bs4(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        chunks: list[str] = []
        for tag in soup.find_all(["h1", "h2", "h3", "p", "li"]):
            text = tag.get_text(" ", strip=True)
            if text:
                chunks.append(text)
        return "\n".join(chunks)

    @staticmethod
    def _normalize_text(text: str) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        return compact
