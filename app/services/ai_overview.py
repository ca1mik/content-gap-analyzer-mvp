import asyncio
import logging

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class AIOverviewProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_ai_overview(self, query: str) -> str:
        cleaned_query = query.strip()
        if not cleaned_query:
            return ""

        prompt = (
            "You are generating a concise and factual AI overview for a web content strategy task.\n"
            "Provide:\n"
            "1) Short summary of intent behind the query\n"
            "2) 5-8 key topics users expect\n"
            "3) Important facts or constraints\n"
            "4) Terms and entities that should be covered\n"
            "Use plain text with short sections."
        )
        user_text = f"Search query: {cleaned_query}"
        overview = await self._chat_completion(prompt, user_text)
        return overview[: self.settings.max_ai_overview_chars].strip()

    async def _chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        if not self.settings.openai_api_key:
            logger.warning("OPENAI_API_KEY is missing, AI overview is unavailable")
            return ""

        endpoint = f"{self.settings.openai_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.openai_model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        max_attempts = self.settings.http_retries + 1
        for attempt in range(max_attempts):
            try:
                timeout = httpx.Timeout(self.settings.http_timeout_seconds, connect=10.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()

                data = response.json()
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if not content:
                    raise ValueError("Empty LLM response")
                return content
            except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
                logger.warning("AI overview request failed on attempt %s: %s", attempt + 1, exc)
                if attempt == max_attempts - 1:
                    return ""
                await asyncio.sleep(0.6 * (2**attempt))

        return ""
