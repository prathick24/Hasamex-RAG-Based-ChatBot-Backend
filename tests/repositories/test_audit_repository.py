import pytest

from src.models import ChatHistory, ErrorLog, LLMUsageLog
from src.repositories.audit_repository import AuditRepository
from src.utils.exceptions.exceptions import DatabaseWriteError, RepositoryError


class FakeResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def scalars(self):
        return iter(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self, results=None) -> None:
        self._queue = list(results or [])
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, stmt, params=None):
        if self._queue:
            return self._queue.pop(0)
        return FakeResult([])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if hasattr(obj, "id"):
                obj.id = 1

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def make_session(*results) -> FakeSession:
    return FakeSession(results)


async def test_add_chat_turn():
    session = make_session()
    repository = AuditRepository(session)
    row_id = await repository.add_chat_turn(
        question="What is the ROI?",
        mode="answer",
        answer="Here is the answer.",
        citations=[{"chunk_id": 3, "snippet": "..."}],
        verification_status=None,
        model="mock-model",
        latency_ms=1250,
    )
    assert row_id == 1
    assert session.committed
    row = session.added[0]
    assert isinstance(row, ChatHistory)
    assert row.question == "What is the ROI?"
    assert row.mode == "answer"
    assert row.answer == "Here is the answer."
    assert row.citations == [{"chunk_id": 3, "snippet": "..."}]
    assert row.model == "mock-model"
    assert row.latency_ms == 1250


async def test_add_error():
    session = make_session()
    repository = AuditRepository(session)
    row_id = await repository.add_error(
        component="qa",
        message="Groq failed",
        exception_type="LLMError",
        endpoint="/api/v1/qa/ask",
        method="POST",
        detail={"question": "hi"},
    )
    assert row_id == 1
    row = session.added[0]
    assert isinstance(row, ErrorLog)
    assert row.level == "error"
    assert row.component == "qa"
    assert row.exception_type == "LLMError"
    assert row.endpoint == "/api/v1/qa/ask"
    assert row.method == "POST"
    assert row.detail == {"question": "hi"}


async def test_add_llm_usage():
    session = make_session()
    repository = AuditRepository(session)
    row_id = await repository.add_llm_usage(
        task="qa_answer",
        model="mock-model",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        latency_ms=900,
        success=True,
    )
    assert row_id == 1
    row = session.added[0]
    assert isinstance(row, LLMUsageLog)
    assert row.task == "qa_answer"
    assert row.total_tokens == 15
    assert row.success is True


async def test_list_chat_history():
    rows = [
        ChatHistory(question="q1", mode="answer", answer="a1", citations=[]),
        ChatHistory(question="q2", mode="quote", answer=None, citations=[]),
    ]
    repository = AuditRepository(make_session(FakeResult(rows)))
    out = await repository.list_chat_history(limit=2)
    assert len(out) == 2
    assert out[0]["question"] == "q1"
    assert out[0]["citations"] == []
    assert out[1]["mode"] == "quote"


async def test_list_error_logs():
    rows = [ErrorLog(level="error", component="themes", message="boom")]
    repository = AuditRepository(make_session(FakeResult(rows)))
    out = await repository.list_error_logs(limit=5)
    assert out[0]["component"] == "themes"
    assert out[0]["message"] == "boom"


async def test_list_llm_usage():
    rows = [LLMUsageLog(task="themes", model="mock-model", success=False)]
    repository = AuditRepository(make_session(FakeResult(rows)))
    out = await repository.list_llm_usage(limit=5)
    assert out[0]["task"] == "themes"
    assert out[0]["success"] is False


async def test_add_raises_database_write_error():
    class BoomSession:
        def add(self, obj):
            raise RuntimeError("db is down")

        async def rollback(self):
            pass

    repository = AuditRepository(BoomSession())
    with pytest.raises(DatabaseWriteError):
        await repository.add_chat_turn(question="q", mode="answer")


async def test_list_raises_repository_error():
    class BoomExecute:
        async def execute(self, stmt, params=None):
            raise RuntimeError("query failed")

    repository = AuditRepository(BoomExecute())
    with pytest.raises(RepositoryError):
        await repository.list_error_logs(limit=5)