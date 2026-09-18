from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

import main
from src.repositories.database import get_db
from src.services.qa_service import detect_quote_intent

@asynccontextmanager
async def _noop_lifespan(app):
    yield


# Neutralise lifespan DB initialisation for fast route tests
main.app.router.lifespan_context = _noop_lifespan


class FakeSession:
    async def execute(self, *args, **kwargs):
        raise AssertionError("execute should be mocked")

    async def get(self, *args, **kwargs):
        raise AssertionError("get should be mocked")


@pytest.fixture
def client(monkeypatch):
    main.app.dependency_overrides.clear()

    def override_get_db():
        return FakeSession()

    main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "hasamex-transcript-analysis"
    assert body["docs"] == "/docs"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_ok(client, monkeypatch):
    from src.repositories import transcript_repository as tr

    async def fake_pgvector(self):
        return True

    async def fake_tables(self):
        return True

    async def fake_count_t(self):
        return 3

    async def fake_count_c(self):
        return 21

    monkeypatch.setattr(tr.TranscriptRepository, "pgvector_available", fake_pgvector)
    monkeypatch.setattr(tr.TranscriptRepository, "tables_available", fake_tables)
    monkeypatch.setattr(tr.TranscriptRepository, "count_transcripts", fake_count_t)
    monkeypatch.setattr(tr.TranscriptRepository, "count_chunks", fake_count_c)

    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["transcripts_count"] == 3
    assert body["chunks_count"] == 21


def test_ready_not_ready(client, monkeypatch):
    from src.repositories import transcript_repository as tr

    async def fake_pgvector(self):
        return False

    monkeypatch.setattr(tr.TranscriptRepository, "pgvector_available", fake_pgvector)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_ingest_ok(client, monkeypatch):
    from src.routes import ingest as ingest_route
    from src.services import ingest_service as ing_svc

    async def fake_ingest_all(self):
        from src.repositories.schema.schemas import IngestionResult

        return IngestionResult(
            transcripts_count=3, chunks_count=21, loaded=True, created_transcripts=3, created_chunks=21
        )

    monkeypatch.setattr(ing_svc.IngestService, "ingest_all", fake_ingest_all)

    response = client.post("/api/v1/transcripts")
    assert response.status_code == 200
    body = response.json()
    assert body["transcripts_count"] == 3
    assert body["chunks_count"] == 21


def test_ingest_error(client, monkeypatch):
    from src.services import ingest_service as ing_svc
    from src.utils.exceptions.exceptions import IngestionError

    async def fake_ingest_all(self):
        raise IngestionError("cannot parse")

    monkeypatch.setattr(ing_svc.IngestService, "ingest_all", fake_ingest_all)
    response = client.post("/api/v1/transcripts")
    assert response.status_code == 500
    assert "cannot parse" in response.json()["detail"]


def test_interview_guide_ok(client, monkeypatch):
    from src.services import interview_guide_service as igs

    async def fake_get(self):
        return []

    monkeypatch.setattr(igs.InterviewGuideService, "get_interview_guide", fake_get)
    response = client.get("/api/v1/analysis/interview-guide")
    assert response.status_code == 200
    assert response.json() == []


def test_themes_ok(client, monkeypatch):
    from src.services import theme_service as ts

    async def fake_get(self):
        return []

    monkeypatch.setattr(ts.ThemeService, "get_themes", fake_get)
    response = client.get("/api/v1/analysis/themes")
    assert response.status_code == 200
    assert response.json() == []


def test_qa_ask_answer_mode(client, monkeypatch):
    from src.repositories.schema.schemas import AnswerModeResponse, Citation
    from src.services import qa_service as qs

    async def fake_ask(self, question, mode=None, top_k=None):
        return AnswerModeResponse(
            question=question,
            mode="answer",
            answer="Training matters.",
            citations=[
                Citation(
                    transcript_file="T.txt",
                    expert_name="Dr. X",
                    market="France",
                    timestamp="00:10",
                    quote="Training matters.",
                )
            ],
        )

    monkeypatch.setattr(qs.QAService, "ask", fake_ask)
    response = client.post("/api/v1/qa/ask", json={"question": "Is training important?", "mode": "answer"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "answer"
    assert body["answer"] == "Training matters."
    assert body["citations"][0]["quote"] == "Training matters."


def test_qa_ask_quote_mode(client, monkeypatch):
    from src.repositories.schema.schemas import QuoteModeResponse, QuoteResponseItem
    from src.services import qa_service as qs

    async def fake_ask(self, question, mode=None, top_k=None):
        return QuoteModeResponse(
            question=question,
            mode="quote",
            answer=None,
            quotes=[
                QuoteResponseItem(
                    quote="verbatim phrase",
                    transcript_file="T.txt",
                    expert_name="Dr. X",
                    market="France",
                    timestamp="00:10",
                    verification_status="verified",
                )
            ],
            citations=[],
        )

    monkeypatch.setattr(qs.QAService, "ask", fake_ask)
    response = client.post(
        "/api/v1/qa/ask",
        json={"question": "give me the exact quote about training", "mode": "quote"},
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "quote"
    assert response.json()["quotes"][0]["quote"] == "verbatim phrase"


def test_qa_ask_validation_error(client):
    response = client.post("/api/v1/qa/ask", json={"question": "", "mode": "bad"})
    assert response.status_code == 422


def test_qa_ask_no_groq_key(client, monkeypatch):
    from src.services import qa_service as qs
    from src.utils.exceptions.exceptions import LLMError

    async def fake_ask(self, question, mode=None, top_k=None):
        raise LLMError("GROQ_API_KEY is not configured")

    monkeypatch.setattr(qs.QAService, "ask", fake_ask)
    response = client.post("/api/v1/qa/ask", json={"question": "Any question"})
    assert response.status_code == 502


def test_detect_quote_intent_covered_in_service_tests():
    assert detect_quote_intent("what is adoption?") is False