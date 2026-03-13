import pytest

from app.core.config import Settings
from app.services.analyzer import ContentAnalyzer


@pytest.mark.asyncio
async def test_gap_detection_fallback_marks_missing_topic() -> None:
    analyzer = ContentAnalyzer(Settings(openai_api_key=None))
    ai_overview = (
        "A good productivity tools guide should cover task management, "
        "time tracking, calendar integration, and pricing tiers."
    )
    page_text = (
        "This article compares task management apps and explains calendar integration. "
        "It does not discuss subscription models."
    )

    gaps = await analyzer.analyze_gaps(ai_overview, page_text)

    assert gaps
    pricing_gap = next(
        (gap for gap in gaps if "pricing" in gap.item.lower() or "subscription" in gap.item.lower()),
        None,
    )
    assert pricing_gap is not None
    assert pricing_gap.status in {"missing", "weak"}
