from pathlib import Path

import pytest

from src.services.interview_guide_service import InterviewGuideService

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATAS = PROJECT_ROOT / "datas"


class FakeEmbedder:
    def embed_one(self, text):
        return [0.1] * 384


class FakeGroq:
    def __init__(self, payload) -> None:
        self._payload = payload
        self.calls = 0

    async def parse_json_completion(self, messages, temperature=0.2, max_tokens=2048):
        self.calls += 1
        return self._payload


class FakeSettings:
    similarity_threshold = 0.5
    llm_model = "mock"
    cache_llm_results = False
    transcript_dir = str(DATAS)


class FakeRepo:
    def __init__(self, transcripts, chunks) -> None:
        self._transcripts = transcripts
        self._chunks = chunks

    async def list_transcripts(self):
        return self._transcripts

    async def get_transcript(self, transcript_id):
        return type(
            "T",
            (),
            {"id": transcript_id, "expert_name": "Dr. X", "filename": "T.txt", "market": "France"},
        )()

    async def similarity_search(self, query_embedding, top_k, transcript_id=None, min_cosine_distance=None):
        return self._chunks


def make_chunk(content="Training matters a lot", timestamp="00:10"):
    return type(
        "C",
        (),
        {
            "content": content,
            "timestamp": timestamp,
            "expert_name": "Dr. X",
            "market": "France",
            "transcript_file": "T.txt",
            "distance": 0.1,
        },
    )()


def make_transcript_record():
    return type(
        "R",
        (),
        {
            "id": 1,
            "expert_name": "Dr. X",
            "filename": "T.txt",
            "market": "France",
            "expert_role": "Surgeon",
            "chunk_count": 1,
        },
    )()


def make_service(payload, chunks=None):
    repo = FakeRepo([make_transcript_record()], chunks or [])
    groq = FakeGroq(payload)
    deps = SimpleNamespace(embedder=FakeEmbedder(), settings=FakeSettings(), groq=groq)
    return InterviewGuideService(repo, deps), groq


class SimpleNamespace:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


async def test_interview_guide_generates_answers(monkeypatch):
    payload = {
        "answer": "Adoption is concentrated in academic hospitals.",
        "citations": [
            {
                "transcript_file": "T.txt",
                "expert_name": "Dr. X",
                "market": "France",
                "timestamp": "00:10",
                "quote": "concentrated in academic hospitals",
            }
        ],
    }
    svc, groq = make_service(
        payload,
        chunks=[make_chunk(content="Adoption is concentrated in academic hospitals and private centres")],
    )

    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: groq)
    entries = await svc.get_interview_guide()
    assert len(entries) == 6
    assert entries[0].question_id == 1
    answer = entries[0].answers[0]
    assert "Adoption is concentrated" in answer.answer
    assert len(answer.citations) == 1
    assert answer.citations[0].quote == "concentrated in academic hospitals"
    assert groq.calls == 6


async def test_interview_guide_not_mentioned_when_no_chunks(monkeypatch):
    svc, groq = make_service({}, chunks=[])
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: groq)
    entries = await svc.get_interview_guide()
    for entry in entries:
        assert entry.answers[0].answer == "Not mentioned in this transcript"
        assert entry.answers[0].citations == []


async def test_interview_guide_fabricated_citations_dropped(monkeypatch):
    payload = {
        "answer": "something",
        "citations": [
            {
                "transcript_file": "T.txt",
                "expert_name": "Dr. X",
                "market": "France",
                "timestamp": "00:10",
                "quote": "not in the source at all",
            }
        ],
    }
    svc, groq = make_service(payload, chunks=[make_chunk()])
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: groq)
    entries = await svc.get_interview_guide()
    assert entries[0].answers[0].citations == []