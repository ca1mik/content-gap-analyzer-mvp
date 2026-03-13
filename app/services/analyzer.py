import asyncio
import json
import logging
import re
from collections import Counter

import httpx

from app.core.config import Settings
from app.db.schemas import ExtractedItem, GapItem

logger = logging.getLogger(__name__)

STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "best",
    "but",
    "can",
    "for",
    "from",
    "have",
    "into",
    "more",
    "most",
    "that",
    "the",
    "their",
    "there",
    "this",
    "tools",
    "with",
    "what",
    "when",
    "where",
    "which",
    "will",
    "your",
    "как",
    "или",
    "для",
    "это",
    "что",
    "если",
    "чтобы",
}


class ContentAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract_entities(
        self, ai_overview_text: str, page_text: str
    ) -> list[ExtractedItem]:
        if not ai_overview_text.strip():
            return []

        prompt = (
            "Extract entities, facts, and concepts from the given text.\n"
            "Return strictly JSON array only.\n"
            'Each item must match: {"text": "string", "type": "entity|fact|concept"}.\n'
            "Return up to 20 items and avoid duplicates."
        )
        user_text = (
            f"AI overview:\n{ai_overview_text[:6000]}\n\n"
            f"Page content excerpt:\n{page_text[:4000]}"
        )
        data = await self._chat_json(prompt, user_text)
        items = self._validate_entities(data)
        if items:
            return items
        return self._heuristic_entities(ai_overview_text, page_text)

    async def analyze_gaps(self, ai_overview_text: str, page_text: str) -> list[GapItem]:
        if not ai_overview_text.strip():
            return []

        prompt = (
            "Compare AI overview with page content and identify coverage gaps.\n"
            "Return strictly JSON array only.\n"
            "Each item must include keys:\n"
            'item, status(missing|weak|covered), evidence_from_ai_overview, evidence_from_page.\n'
            "Return up to 15 items."
        )
        user_text = (
            f"AI overview:\n{ai_overview_text[:6000]}\n\n"
            f"Page content:\n{page_text[:6000]}"
        )
        data = await self._chat_json(prompt, user_text)
        gaps = self._validate_gaps(data)
        if gaps:
            return gaps
        return self._heuristic_gap_analysis(ai_overview_text, page_text)

    async def generate_recommendations(self, gaps: list[GapItem]) -> list[str]:
        if not gaps:
            return []

        prompt = (
            "Generate 5-10 concrete recommendations tied directly to each gap.\n"
            "Every recommendation must explain what to add/improve and why.\n"
            "Return strictly JSON array of strings only."
        )
        gap_payload = json.dumps([gap.model_dump() for gap in gaps], ensure_ascii=False)
        user_text = f"Gaps:\n{gap_payload}"

        data = await self._chat_json(prompt, user_text)
        recommendations = self._validate_recommendations(data)
        if recommendations:
            return recommendations[:10]
        return self._heuristic_recommendations(gaps)

    async def _chat_text(self, system_prompt: str, user_prompt: str) -> str:
        if not self.settings.openai_api_key:
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
                if content:
                    return content
                raise ValueError("Empty LLM response")
            except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
                logger.warning("Analyzer LLM request failed on attempt %s: %s", attempt + 1, exc)
                if attempt == max_attempts - 1:
                    return ""
                await asyncio.sleep(0.6 * (2**attempt))

        return ""

    async def _chat_json(self, system_prompt: str, user_prompt: str) -> list | dict | None:
        response_text = await self._chat_text(system_prompt, user_prompt)
        if not response_text:
            return None
        parsed = self._parse_json(response_text)
        if parsed is None:
            logger.warning("Failed to parse model response as JSON")
        return parsed

    @staticmethod
    def _parse_json(text: str) -> list | dict | None:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
            stripped = re.sub(r"\n?```$", "", stripped).strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _normalize_array(data: list | dict | None, expected_key: str) -> list:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            maybe_items = data.get(expected_key)
            if isinstance(maybe_items, list):
                return maybe_items
            for key in ("items", "entities", "gaps", "recommendations"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _validate_entities(self, data: list | dict | None) -> list[ExtractedItem]:
        raw_items = self._normalize_array(data, "entities")
        allowed = {"entity", "fact", "concept"}
        result: list[ExtractedItem] = []
        seen: set[tuple[str, str]] = set()

        for item in raw_items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            item_type = str(item.get("type", "")).strip().lower()
            if not text or item_type not in allowed:
                continue
            key = (text.lower(), item_type)
            if key in seen:
                continue
            seen.add(key)
            result.append(ExtractedItem(text=text, type=item_type))
            if len(result) >= 20:
                break
        return result

    def _validate_gaps(self, data: list | dict | None) -> list[GapItem]:
        raw_items = self._normalize_array(data, "gaps")
        allowed_status = {"missing", "weak", "covered"}
        result: list[GapItem] = []

        for item in raw_items:
            if not isinstance(item, dict):
                continue
            gap_item = str(item.get("item", "")).strip()
            status = str(item.get("status", "")).strip().lower()
            evidence_ai = str(item.get("evidence_from_ai_overview", "")).strip()
            evidence_page = str(item.get("evidence_from_page", "")).strip()
            if not gap_item or status not in allowed_status:
                continue
            result.append(
                GapItem(
                    item=gap_item,
                    status=status,
                    evidence_from_ai_overview=evidence_ai,
                    evidence_from_page=evidence_page,
                )
            )
            if len(result) >= 15:
                break
        return result

    def _validate_recommendations(self, data: list | dict | None) -> list[str]:
        raw_items = self._normalize_array(data, "recommendations")
        result: list[str] = []
        for item in raw_items:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text:
                result.append(text)
        return result

    def _heuristic_entities(
        self, ai_overview_text: str, page_text: str
    ) -> list[ExtractedItem]:
        result: list[ExtractedItem] = []
        seen: set[tuple[str, str]] = set()

        named = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", ai_overview_text)
        for value in named[:8]:
            key = (value.lower(), "entity")
            if key in seen:
                continue
            seen.add(key)
            result.append(ExtractedItem(text=value, type="entity"))

        sentences = self._split_sentences(ai_overview_text + " " + page_text[:2000])
        for sentence in sentences:
            if any(ch.isdigit() for ch in sentence):
                fact = sentence.strip()[:180]
                if not fact:
                    continue
                key = (fact.lower(), "fact")
                if key in seen:
                    continue
                seen.add(key)
                result.append(ExtractedItem(text=fact, type="fact"))
            if len(result) >= 16:
                break

        tokens = self._keywords(ai_overview_text, max_terms=8)
        for token in tokens:
            key = (token.lower(), "concept")
            if key in seen:
                continue
            seen.add(key)
            result.append(ExtractedItem(text=token, type="concept"))
            if len(result) >= 20:
                break

        return result

    def _heuristic_gap_analysis(self, ai_overview_text: str, page_text: str) -> list[GapItem]:
        sentences = self._split_sentences(ai_overview_text)
        if not sentences:
            return []

        page_lower = page_text.lower()
        gaps: list[GapItem] = []
        for sentence in sentences[:12]:
            keywords = self._keywords(sentence, max_terms=6)
            if not keywords:
                continue

            matches = [kw for kw in keywords if kw.lower() in page_lower]
            coverage_ratio = len(matches) / len(keywords)
            if coverage_ratio >= 0.7:
                status = "covered"
            elif coverage_ratio >= 0.35:
                status = "weak"
            else:
                status = "missing"

            evidence_page = ""
            if matches:
                evidence_page = self._extract_snippet(page_text, matches[0])

            item = sentence.strip()
            if len(item) > 180:
                item = f"{item[:177]}..."
            gaps.append(
                GapItem(
                    item=item,
                    status=status,
                    evidence_from_ai_overview=sentence.strip()[:300],
                    evidence_from_page=evidence_page,
                )
            )

        priority = {"missing": 0, "weak": 1, "covered": 2}
        gaps.sort(key=lambda g: priority[g.status])
        return gaps[:10]

    def _heuristic_recommendations(self, gaps: list[GapItem]) -> list[str]:
        recommendations: list[str] = []
        target_gaps = [gap for gap in gaps if gap.status in {"missing", "weak"}]

        for gap in target_gaps:
            if gap.status == "missing":
                recommendations.append(
                    f"Add a dedicated section about '{gap.item}' because this topic appears in AI overview but is not covered on the page."
                )
            else:
                recommendations.append(
                    f"Expand coverage of '{gap.item}' with practical details and examples, because current page coverage is weaker than AI overview."
                )
            if len(recommendations) >= 10:
                break

        if len(recommendations) < 5:
            for gap in gaps:
                recommendations.append(
                    f"Improve clarity around '{gap.item}' by adding concise explanations and internal structure."
                )
                if len(recommendations) >= 5:
                    break

        return recommendations[:10]

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def _keywords(text: str, max_terms: int = 8) -> list[str]:
        words = re.findall(r"[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-]{2,}", text.lower())
        filtered = [word for word in words if word not in STOPWORDS and len(word) > 3]
        counts = Counter(filtered)
        return [word for word, _ in counts.most_common(max_terms)]

    @staticmethod
    def _extract_snippet(text: str, keyword: str, radius: int = 120) -> str:
        lower = text.lower()
        needle = keyword.lower()
        idx = lower.find(needle)
        if idx == -1:
            return ""
        start = max(0, idx - radius)
        end = min(len(text), idx + len(keyword) + radius)
        snippet = text[start:end].strip()
        return snippet[:260]
