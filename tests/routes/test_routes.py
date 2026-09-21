from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

import main
from src.repositories.database import get_db

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


def test_upload_transcripts_ok(client, monkeypatch):
    from src.services import ingest_service as ing_svc

    async def fake_ingest_single_file(self, filename, content):
        return {"transcript_id": 42, "replaced": False, "version": 1, "chunk_count": 7}

    monkeypatch.setattr(ing_svc.IngestService, "ingest_single_file", fake_ingest_single_file)
    response = client.post(
        "/api/v1/transcripts/upload",
        files=[
            ("files", ("a.txt", b"some content", "text/plain")),
            ("files", ("b.txt", b"other content", "text/plain")),
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 2
    assert body["succeeded"] == 2
    assert body["results"][0]["status"] == "uploaded"
    assert body["results"][0]["transcript_id"] == 42
    assert body["results"][0]["version"] == 1


def test_upload_transcripts_replaced(client, monkeypatch):
    from src.services import ingest_service as ing_svc

    async def fake_ingest_single_file(self, filename, content):
        return {"transcript_id": 43, "replaced": True, "version": 2, "chunk_count": 5}

    monkeypatch.setattr(ing_svc.IngestService, "ingest_single_file", fake_ingest_single_file)
    response = client.post(
        "/api/v1/transcripts/upload",
        files=[("files", ("a.txt", b"content", "text/plain"))],
    )
    body = response.json()
    assert body["succeeded"] == 1
    assert body["results"][0]["status"] == "replaced"
    assert body["results"][0]["version"] == 2


def test_upload_transcripts_non_txt_rejected(client):
    response = client.post(
        "/api/v1/transcripts/upload",
        files=[("files", ("b.md", b"# note", "text/markdown"))],
    )
    body = response.json()
    assert body["succeeded"] == 0
    assert body["results"][0]["status"] == "error"
    assert "Only .txt files" in body["results"][0]["reason"]


def test_upload_transcripts_validation_error(client, monkeypatch):
    from src.services import ingest_service as ing_svc
    from src.utils.exceptions.exceptions import ValidationError

    async def fake_ingest_single_file(self, filename, content):
        raise ValidationError("Could not parse expert metadata from header")

    monkeypatch.setattr(ing_svc.IngestService, "ingest_single_file", fake_ingest_single_file)
    response = client.post(
        "/api/v1/transcripts/upload",
        files=[("files", ("a.txt", b"garbage", "text/plain"))],
    )
    body = response.json()
    assert body["succeeded"] == 0
    assert body["results"][0]["status"] == "error"
    assert "Could not parse" in body["results"][0]["reason"]


def test_list_transcripts_ok(client, monkeypatch):
    from src.repositories.schema.schemas import TranscriptRecord
    from src.services import ingest_service as ing_svc

    async def fake_list(self):
        return [
            TranscriptRecord(
                id=1, filename="a.txt", expert_name="X", expert_role=None, market="M", chunk_count=7
            )
        ]

    monkeypatch.setattr(ing_svc.IngestService, "list_ingested", fake_list)
    response = client.get("/api/v1/transcripts")
    assert response.status_code == 200
    body = response.json()
    assert body["transcripts"][0]["filename"] == "a.txt"


def test_seed_transcripts_skips_when_db_has_data(monkeypatch):
    import asyncio

    import main as main_module
    from src.repositories.transcript_repository import TranscriptRepository
    from src.services.ingest_service import IngestService
    from src.settings import Settings

    class FakeCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return False

    async def fake_count(self):
        return 3

    async def fake_ingest_all(self):
        raise AssertionError("ingest_all must not run when transcripts already exist")

    monkeypatch.setattr(main_module.db, "session", lambda: FakeCtx())
    monkeypatch.setattr(TranscriptRepository, "count_transcripts", fake_count)
    monkeypatch.setattr(IngestService, "ingest_all", fake_ingest_all)

    asyncio.run(main_module._seed_transcripts(Settings(seed_on_startup=True)))


def test_seed_transcripts_ingests_empty_db(monkeypatch):
    import asyncio

    import main as main_module
    from src.repositories.schema.schemas import IngestionResult
    from src.repositories.transcript_repository import TranscriptRepository
    from src.services.ingest_service import IngestService
    from src.settings import Settings

    class FakeCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return False

    async def fake_count(self):
        return 0

    calls = []

    async def fake_ingest_all(self):
        calls.append(True)
        return IngestionResult(
            transcripts_count=3,
            chunks_count=21,
            loaded=True,
            created_transcripts=3,
            created_chunks=21,
        )

    class FakeDeps:
        embedder = object()

    async def fake_get_service_deps():
        return FakeDeps()

    monkeypatch.setattr(main_module.db, "session", lambda: FakeCtx())
    monkeypatch.setattr(TranscriptRepository, "count_transcripts", fake_count)
    monkeypatch.setattr(IngestService, "ingest_all", fake_ingest_all)
    monkeypatch.setattr("src.services.dependencies.get_service_deps", fake_get_service_deps)

    asyncio.run(main_module._seed_transcripts(Settings(seed_on_startup=True)))

    assert calls == [True]


def test_qa_ask_returns_answer_with_quotes(client, monkeypatch):
    from src.repositories.schema.schemas import AnswerModeResponse, Citation, QuoteResponseItem
    from src.services import qa_service as qs

    async def fake_ask(self, question, top_k=None):
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
            quotes=[
                QuoteResponseItem(
                    quote="Training is essential",
                    transcript_file="T.txt",
                    expert_name="Dr. X",
                    market="France",
                    timestamp="00:10",
                    verification_status="verified",
                )
            ],
        )

    monkeypatch.setattr(qs.QAService, "ask", fake_ask)
    response = client.post("/api/v1/qa/ask", json={"question": "Is training important?"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "answer"
    assert body["answer"] == "Training matters."
    assert body["citations"][0]["quote"] == "Training matters."
    assert body["quotes"][0]["quote"] == "Training is essential"
    assert body["quotes"][0]["verification_status"] == "verified"


def test_qa_ask_validation_error(client):
    response = client.post("/api/v1/qa/ask", json={"question": ""})
    assert response.status_code == 422


def test_qa_ask_no_groq_key(client, monkeypatch):
    from src.services import qa_service as qs
    from src.utils.exceptions.exceptions import LLMError

    async def fake_ask(self, question, top_k=None):
        raise LLMError("GROQ_API_KEY is not configured")

    monkeypatch.setattr(qs.QAService, "ask", fake_ask)
    response = client.post("/api/v1/qa/ask", json={"question": "Any question"})
    assert response.status_code == 502