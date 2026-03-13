import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.database import get_db
from app.db.models import AnalysisRun
from app.db.schemas import AnalyzeRequest, AnalyzeResponse, RunDetail, RunSummary
from app.services.ai_overview import AIOverviewProvider
from app.services.analyzer import ContentAnalyzer
from app.services.page_parser import PageParser

logger = logging.getLogger(__name__)

router = APIRouter()


def get_ai_provider(settings: Settings = Depends(get_settings)) -> AIOverviewProvider:
    return AIOverviewProvider(settings)


def get_page_parser(settings: Settings = Depends(get_settings)) -> PageParser:
    return PageParser(settings)


def get_content_analyzer(settings: Settings = Depends(get_settings)) -> ContentAnalyzer:
    return ContentAnalyzer(settings)


def _decode_json_array(raw_value: str | None) -> list:
    if not raw_value:
        return []
    try:
        data = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    payload: AnalyzeRequest,
    db: Session = Depends(get_db),
    ai_provider: AIOverviewProvider = Depends(get_ai_provider),
    parser: PageParser = Depends(get_page_parser),
    analyzer: ContentAnalyzer = Depends(get_content_analyzer),
) -> AnalyzeResponse:
    query = payload.query.strip()
    url = str(payload.url)
    errors: list[str] = []

    ai_overview_text = await ai_provider.get_ai_overview(query)

    try:
        page_text = await parser.extract_page_text(url)
    except Exception as exc:  # pragma: no cover
        logger.exception("Page parsing failed: %s", exc)
        page_text = ""
        errors.append(f"page_parser_error: {exc}")

    entities = []
    gaps = []
    recommendations = []
    status = "completed"

    if not ai_overview_text:
        status = "no_ai_overview"
    else:
        try:
            entities = await analyzer.extract_entities(ai_overview_text, page_text)
        except Exception as exc:  # pragma: no cover
            logger.exception("Entity extraction failed: %s", exc)
            errors.append(f"entity_extraction_error: {exc}")

        try:
            gaps = await analyzer.analyze_gaps(ai_overview_text, page_text)
        except Exception as exc:  # pragma: no cover
            logger.exception("Gap analysis failed: %s", exc)
            errors.append(f"gap_analysis_error: {exc}")

        try:
            recommendations = await analyzer.generate_recommendations(gaps)
        except Exception as exc:  # pragma: no cover
            logger.exception("Recommendation generation failed: %s", exc)
            errors.append(f"recommendation_error: {exc}")

    if errors and status == "completed":
        status = "partial"

    run = AnalysisRun(
        query=query,
        url=url,
        status=status,
        ai_overview_text=ai_overview_text,
        entities=json.dumps([item.model_dump() for item in entities], ensure_ascii=False),
        gaps=json.dumps([item.model_dump() for item in gaps], ensure_ascii=False),
        recommendations=json.dumps(recommendations, ensure_ascii=False),
        error_message="; ".join(errors) if errors else None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    return AnalyzeResponse(
        run_id=run.id,
        query=run.query,
        url=run.url,
        status=run.status,
        ai_overview_text=run.ai_overview_text or "",
        entities=entities,
        gaps=gaps,
        recommendations=recommendations,
        timestamp=run.timestamp,
    )


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[RunSummary]:
    rows = (
        db.query(AnalysisRun).order_by(AnalysisRun.timestamp.desc()).limit(limit).all()
    )
    return [RunSummary.model_validate(row) for row in rows]


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: int, db: Session = Depends(get_db)) -> RunDetail:
    row = db.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")

    entities = _decode_json_array(row.entities)
    gaps = _decode_json_array(row.gaps)
    recommendations = _decode_json_array(row.recommendations)

    return RunDetail(
        id=row.id,
        query=row.query,
        url=row.url,
        status=row.status,
        timestamp=row.timestamp,
        ai_overview_text=row.ai_overview_text or "",
        entities=entities,
        gaps=gaps,
        recommendations=recommendations,
        error_message=row.error_message,
    )
