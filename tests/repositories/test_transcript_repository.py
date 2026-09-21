import pytest

from src.repositories.transcript_repository import TranscriptRepository
from src.utils.exceptions.exceptions import (
    DatabaseWriteError,
    RepositoryError,
    TranscriptNotFoundError,
)


class FakeResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def scalars(self):
        return iter(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class FakeSession:
    """A minimal async session that records executed statements."""

    def __init__(self, results=None) -> None:
        self._queue = list(results or [])
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, stmt, params=None):
        if self._queue:
            return self._queue.pop(0)
        return FakeResult([])

    def add_all(self, objects):
        self.added.extend(objects)

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

    @property
    def new(self):
        return self.added


def make_session(*results) -> FakeSession:
    return FakeSession(results)


async def test_get_transcript_not_found():
    repo = TranscriptRepository(make_session(FakeResult([])))
    with pytest.raises(TranscriptNotFoundError):
        await repo.get_transcript(1)


async def test_get_transcript_found():
    transcript = type("T", (), {"id": 7})()
    repo = TranscriptRepository(make_session(FakeResult([transcript])))
    found = await repo.get_transcript(7)
    assert found.id == 7


async def test_list_transcripts():
    transcript = type(
        "T",
        (),
        {
            "id": 1,
            "filename": "a.txt",
            "expert_name": "X",
            "expert_role": None,
            "market": "M",
            "chunk_count": 0,
        },
    )()
    repo = TranscriptRepository(make_session(FakeResult([transcript])))
    records = await repo.list_transcripts()
    assert records[0].filename == "a.txt"


async def test_count_transcripts_and_chunks():
    repo = TranscriptRepository(make_session(FakeResult([3]), FakeResult([21])))
    assert await repo.count_transcripts() == 3
    assert await repo.count_chunks() == 21


async def test_add_transcripts_failure_rolls_back():
    class BoomSession(FakeSession):
        async def flush(self):
            raise RuntimeError("boom")

    session = BoomSession()
    repo = TranscriptRepository(session)
    with pytest.raises(DatabaseWriteError):
        await repo.add_transcripts([{"filename": "a.txt", "expert_name": "X", "market": "M"}])
    assert session.rolled_back


async def test_pgvector_available_true():
    repo = TranscriptRepository(make_session(FakeResult(["vector"])))
    assert await repo.pgvector_available() is True


async def test_pgvector_available_false():
    repo = TranscriptRepository(make_session(FakeResult([None])))
    assert await repo.pgvector_available() is False


async def test_pgvector_available_db_error():
    class BoomSession(FakeSession):
        async def execute(self, stmt, params=None):
            raise RuntimeError("down")

    repo = TranscriptRepository(BoomSession())
    assert await repo.pgvector_available() is False


async def test_tables_available_true():
    repo = TranscriptRepository(make_session(FakeResult([1]), FakeResult([1])))
    assert await repo.tables_available() is True


async def test_tables_available_false():
    repo = TranscriptRepository(make_session(FakeResult([1]), FakeResult([None])))
    assert await repo.tables_available() is False


async def test_similarity_search_empty():
    repo = TranscriptRepository(make_session(FakeResult([])))
    results = await repo.similarity_search([0.1] * 384, top_k=5)
    assert results == []


async def test_similarity_search_db_error():
    class BoomSession(FakeSession):
        async def execute(self, stmt, params=None):
            raise RuntimeError("vector search down")

    repo = TranscriptRepository(BoomSession())
    with pytest.raises(RepositoryError):
        await repo.similarity_search([0.1] * 384, top_k=5)


async def test_question_search_empty():
    repo = TranscriptRepository(make_session(FakeResult([])))
    results = await repo.question_search([0.1] * 384, top_k=2)
    assert results == []


async def test_question_search_returns_chunks():
    row = _make_row(chunk_id=2, content="Q: adoption?\nA: steady growth")
    repo = TranscriptRepository(make_session(FakeResult([row])))
    results = await repo.question_search([0.1] * 384, top_k=2, transcript_id=1)
    assert results[0].content == "Q: adoption?\nA: steady growth"


async def test_question_search_db_error():
    class BoomSession(FakeSession):
        async def execute(self, stmt, params=None):
            raise RuntimeError("question vector search down")

    repo = TranscriptRepository(BoomSession())
    with pytest.raises(RepositoryError):
        await repo.question_search([0.1] * 384, top_k=2)


async def test_keyword_search_returns_chunks():
    row = _make_row(chunk_id=1, content="cost is the first barrier")
    repo = TranscriptRepository(make_session(FakeResult([row])))
    results = await repo.keyword_search("cost barrier", 5)
    assert results[0].content == "cost is the first barrier"


async def test_keyword_search_db_error():
    class BoomSession(FakeSession):
        async def execute(self, stmt, params=None):
            raise RuntimeError("down")

    repo = TranscriptRepository(BoomSession())
    with pytest.raises(RepositoryError):
        await repo.keyword_search("query", 5)


async def test_ingest_maps_filename_to_transcript_id():
    class Session(FakeSession):
        def __init__(self):
            super().__init__()
            self.step = 0

        async def execute(self, stmt, params=None):
            self.step += 1
            if "GROUP BY" in str(stmt):
                return FakeResult([])
            if self.step >= 4:
                return FakeResult([1])
            return FakeResult([])

    session = Session()
    repo = TranscriptRepository(session)
    result = await repo.ingest(
        transcript_records=[{"filename": "a.txt", "expert_name": "X", "market": "M"}],
        all_chunks=[
            {
                "filename": "a.txt",
                "speaker": "Expert",
                "speaker_index": "EX_00",
                "timestamp": "00:01",
                "content": "hello",
                "embedding": [0.1] * 384,
            }
        ],
    )
    assert result.loaded is True
    assert session.committed


async def test_delete_all_transcripts_commits():
    session = FakeSession([])
    repo = TranscriptRepository(session)
    await repo.delete_all_transcripts()
    assert session.committed


async def test_get_next_version_default_one():
    repo = TranscriptRepository(make_session(FakeResult([None])))
    assert await repo.get_next_version("a.txt") == 1


async def test_get_next_version_increments():
    repo = TranscriptRepository(make_session(FakeResult([2])))
    assert await repo.get_next_version("a.txt") == 3


async def test_upload_version_new_file():
    session = make_session(FakeResult([]), FakeResult([None]))
    repo = TranscriptRepository(session)
    transcript_id, replaced, version = await repo.upload_version(
        {"filename": "a.txt", "expert_name": "X", "expert_role": None, "market": "M"},
        [],
    )
    assert transcript_id == 1
    assert replaced is False
    assert version == 1
    assert session.committed


async def test_upload_version_replaces_active_file():
    existing = type("T", (), {"id": 5, "is_active": True})()
    session = make_session(FakeResult([existing]), FakeResult([1]))
    repo = TranscriptRepository(session)
    transcript_id, replaced, version = await repo.upload_version(
        {"filename": "a.txt", "expert_name": "X", "expert_role": None, "market": "M"},
        [],
    )
    assert transcript_id == 1
    assert replaced is True
    assert version == 2
    assert existing.is_active is False
    assert session.committed


async def test_upload_version_stores_chunk_count():
    session = make_session(FakeResult([]), FakeResult([None]))
    repo = TranscriptRepository(session)
    await repo.upload_version(
        {"filename": "a.txt", "expert_name": "X", "expert_role": None, "market": "M"},
        [
            {
                "speaker": "Expert",
                "speaker_index": "EX_00",
                "timestamp": "00:01",
                "content": "hi",
                "embedding": [0.1] * 384,
            }
        ],
    )
    assert session.added[0].chunk_count == 1


def _make_row(chunk_id=1, content="x"):
    row = type("Row", (), {})()
    row.Chunk = type(
        "Chunk", (), {"id": chunk_id, "timestamp": "00:01", "content": content, "transcript_id": 1}
    )()
    row.filename = "a.txt"
    row.expert_name = "X"
    row.market = "M"
    row.distance = 0.5
    return row
