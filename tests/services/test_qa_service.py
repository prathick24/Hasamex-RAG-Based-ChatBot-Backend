import pytest

from src.services.qa_service import QAService, detect_quote_intent


class FakeRepo:
    def __init__(self) -> None:
        self.semantic: list = []
        self.keyword: list = []

    async def similarity_search(self, query_embedding, top_k, transcript_id=None, min_cosine_distance=None):
        return self.semantic

    async def keyword_search(self, query, top_k, transcript_id=None):
        return self.keyword


class FakeEmbedder:
    def embed_one(self, text):
        return [0.1] * 384


class FakeSettings:
    top_k = 5
    similarity_threshold = 0.5
    llm_model = "mock-model"
    cache_llm_results = False


class FakeGroq:
    def __init__(self, payload) -> None:
        self._payload = payload

    async def parse_json_completion(self, messages, temperature=0.2, max_tokens=2048):
        return self._payload


def chunk(chunk_id=1, expert="Dr. X", timestamp="00:10", content="Training is essential", distance=0.1, transcript_file="T.txt", market="France"):
    return type(
        "Chunk",
        (),
        {
            "chunk_id": chunk_id,
            "expert_name": expert,
            "timestamp": timestamp,
            "content": content,
            "distance": distance,
            "transcript_file": transcript_file,
            "market": market,
        },
    )()


class Dependencies:
    def __init__(self, payload=None, semantic=None, keyword=None) -> None:
        self.embedder = FakeEmbedder()
        self.settings = FakeSettings()
        self.repo = FakeRepo()
        self.repo.semantic = semantic or []
        self.repo.keyword = keyword or []
        self._payload = payload

    @property
    def groq(self):
        return FakeGroq(self._payload)


def build_service(payload=None, semantic=None, keyword=None):
    deps = Dependencies(payload, semantic, keyword)
    return QAService(deps.repo, deps)


async def test_answer_with_chunks_and_citations(monkeypatch):
    svc = build_service(
        payload={
            "answer": "Barriers include capital budgets.",
            "citations": [
                {
                    "transcript_file": "T",
                    "expert_name": "Dr. X",
                    "market": "F",
                    "timestamp": "00:10",
                    "quote": "capital budgets",
                }
            ],
        },
        semantic=[chunk(content="Capital budgets are the main barrier")],
    )
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: svc._deps.groq)
    result = await svc.answer("What are barriers?", top_k=3)
    assert result.mode == "answer"
    assert "Barriers include" in result.answer
    assert len(result.citations) == 1


async def test_answer_returns_not_mentioned_with_empty_chunks():
    svc = build_service(semantic=[])
    result = await svc.answer("Random question")
    assert result.answer == "Not mentioned in the available transcripts."
    assert result.citations == []


async def test_answer_fallback_when_llm_blank(monkeypatch):
    svc = build_service(payload={"answer": "", "citations": []}, semantic=[chunk()])
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: svc._deps.groq)
    result = await svc.answer("q")
    assert result.answer == "Not mentioned in the available transcripts."


async def test_quote_mode_returns_verbatim_chunks():
    svc = build_service(
        semantic=[chunk(content="Exact phrase about budget", distance=0.1)],
        keyword=[chunk(content="Exact phrase about budget", distance=None, chunk_id=1)],
    )
    result = await svc.quote("exact quote about budget approval")
    assert result.mode == "quote"
    assert len(result.quotes) == 1
    assert result.quotes[0].quote == "Exact phrase about budget"
    assert result.quotes[0].verification_status == "verified"


async def test_quote_mode_merges_and_dedupes():
    svc = build_service(
        semantic=[
            chunk(content="A", chunk_id=1),
            chunk(content="B", chunk_id=2, distance=0.2),
        ],
        keyword=[chunk(content="A", chunk_id=1)],
    )
    result = await svc.quote("quote something")
    assert len(result.quotes) == 2


async def test_quote_mode_empty():
    svc = build_service(semantic=[], keyword=[])
    result = await svc.quote("quote nothing")
    assert result.quotes == []
    assert result.citations == []


def test_detect_quote_intent():
    assert detect_quote_intent("give me the exact quote about budget approval") is True
    assert detect_quote_intent("can you quote what she said about barriers") is True
    assert detect_quote_intent("what did Anna say exactly about cost") is True
    assert detect_quote_intent("What slows down adoption in Germany?") is False
    assert detect_quote_intent("Is training important?") is False


async def test_ask_respects_explicit_mode():
    svc = build_service(semantic=[])
    result = await svc.ask("Is training important?", mode="answer")
    assert result.mode == "answer"
    assert result.answer == "Not mentioned in the available transcripts."


async def test_ask_auto_detects_quote():
    svc = build_service(semantic=[chunk()])
    result = await svc.ask("give me the exact quote about training")
    assert result.mode == "quote"