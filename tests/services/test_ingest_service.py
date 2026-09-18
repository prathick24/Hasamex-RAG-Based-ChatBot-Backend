from pathlib import Path

import pytest

from src.services.ingest_service import IngestService
from src.utils.exceptions.exceptions import IngestionError

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATAS = PROJECT_ROOT / "datas"


class FakeRepo:
    def __init__(self) -> None:
        self.ingested = None
        self.result = None

    async def ingest(self, transcript_records, all_chunks):
        self.ingested = (transcript_records, all_chunks)
        return self.result


class FakeSettings:
    transcript_dir = str(DATAS)


class FakeEmbedder:
    def embed(self, texts):
        return [[0.1] * 384 for _ in texts]


def make_service(transcript_dir=None) -> IngestService:
    settings = FakeSettings()
    if transcript_dir:
        settings.transcript_dir = transcript_dir
    repo = FakeRepo()
    return IngestService(repo, FakeEmbedder(), settings)


def test_discover_files_excludes_interview_guide():
    svc = make_service()
    files = svc._discover_files()
    names = [f.name for f in files]
    assert "Interview_Guide.txt" not in names
    assert "Transcript_1_France.txt" in names
    assert len(names) == 3


def test_discover_files_missing_dir_raises(tmp_path):
    svc = make_service(str(tmp_path / "nope"))
    with pytest.raises(IngestionError):
        svc._discover_files()


def test_discover_files_empty_dir_raises(tmp_path):
    svc = make_service(str(tmp_path))
    with pytest.raises(IngestionError):
        svc._discover_files()


async def test_ingest_all_flows(tmp_path):
    fake_transcript = tmp_path / "Transcript_X.txt"
    fake_transcript.write_text(
        "Expert 9 \u2013 Dr. Test\nRole: Surgeon\nMarket: Spain\n\n"
        "00:00\nInterviewer: hello\n\n00:05\nDr. Test: adoption is steady\n",
        encoding="utf-8",
    )
    svc = make_service(str(tmp_path))
    svc._repository.result = dict(ingested=True)
    result = await svc.ingest_all()
    assert result["ingested"] is True
    transcripts, chunks = svc._repository.ingested
    assert transcripts[0]["expert_name"] == "Dr. Test"
    assert chunks[0]["content"] == "adoption is steady"
    assert len(chunks[0]["embedding"]) == 384


async def test_ingest_embeds_all_expert_chunks():
    svc = make_service()
    chunks = [
        {"content": "one", "filename": "Transcript_1_France.txt"},
        {"content": "two", "filename": "Transcript_2_Germany.txt"},
    ]
    await svc._embed_chunks(chunks)
    assert all("embedding" in c for c in chunks)