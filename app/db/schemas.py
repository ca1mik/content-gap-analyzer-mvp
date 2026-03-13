from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field


class AnalyzeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    url: AnyHttpUrl


class ExtractedItem(BaseModel):
    text: str = Field(min_length=1)
    type: Literal["entity", "fact", "concept"]


class GapItem(BaseModel):
    item: str = Field(min_length=1)
    status: Literal["missing", "weak", "covered"]
    evidence_from_ai_overview: str = ""
    evidence_from_page: str = ""


class AnalyzeResponse(BaseModel):
    run_id: int
    query: str
    url: str
    status: str
    ai_overview_text: str
    entities: list[ExtractedItem]
    gaps: list[GapItem]
    recommendations: list[str]
    timestamp: datetime


class RunSummary(BaseModel):
    id: int
    query: str
    url: str
    status: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class RunDetail(BaseModel):
    id: int
    query: str
    url: str
    status: str
    timestamp: datetime
    ai_overview_text: str
    entities: list[ExtractedItem]
    gaps: list[GapItem]
    recommendations: list[str]
    error_message: str | None = None
