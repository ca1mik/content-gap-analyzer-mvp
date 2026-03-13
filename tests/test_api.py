from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import get_ai_provider, get_content_analyzer, get_page_parser
from app.db.database import Base, get_db
from app.db.schemas import ExtractedItem, GapItem
from app.main import app


class FakeAIProvider:
    async def get_ai_overview(self, query: str) -> str:
        return f"Overview for: {query}. Include automation, integrations, and pricing."


class FakePageParser:
    async def extract_page_text(self, url: str) -> str:
        return "The page covers automation and integrations."


class FakeAnalyzer:
    async def extract_entities(self, ai_overview_text: str, page_text: str) -> list[ExtractedItem]:
        return [
            ExtractedItem(text="automation", type="concept"),
            ExtractedItem(text="integrations", type="concept"),
        ]

    async def analyze_gaps(self, ai_overview_text: str, page_text: str) -> list[GapItem]:
        return [
            GapItem(
                item="pricing details",
                status="missing",
                evidence_from_ai_overview="AI overview mentions pricing",
                evidence_from_page="No pricing information on page",
            )
        ]

    async def generate_recommendations(self, gaps: list[GapItem]) -> list[str]:
        return [
            "Add a pricing section because AI overview expects pricing details but page content does not cover it."
        ]


def build_test_db() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )
    Base.metadata.create_all(bind=engine)
    return testing_session_local


def test_api_happy_path() -> None:
    session_local = build_test_db()

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider()
    app.dependency_overrides[get_page_parser] = lambda: FakePageParser()
    app.dependency_overrides[get_content_analyzer] = lambda: FakeAnalyzer()

    client = TestClient(app)

    response = client.post(
        "/analyze",
        json={"query": "best productivity tools", "url": "https://example.com/article"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["query"] == "best productivity tools"
    assert payload["entities"]
    assert payload["gaps"]
    assert payload["recommendations"]

    list_response = client.get("/runs")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    run_id = payload["run_id"]
    detail_response = client.get(f"/runs/{run_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == run_id

    app.dependency_overrides.clear()
