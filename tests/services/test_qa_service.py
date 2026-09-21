from src.services.qa_service import (
    NO_CONTEXT_FALLBACK,
    SCOPE_REPLY,
    QAService,
    detect_off_topic,
)
from src.utils.exceptions.exceptions import ApplicationError


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
    def __init__(self, payload, scope_text, fail_scope=False) -> None:
        self._payload = payload
        self._scope_text = scope_text
        self._fail_scope = fail_scope
        self.create_completion_calls = 0

    async def parse_json_completion(self, messages, temperature=0.2, max_tokens=2048, task=None):
        return self._payload

    async def create_completion(
        self, messages, temperature=0.2, max_tokens=1024, response_format=None, task=None
    ):
        self.create_completion_calls += 1
        if self._fail_scope:
            raise ApplicationError("scope reply failed")
        return {"content": self._scope_text}


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
    def __init__(
        self, payload=None, semantic=None, keyword=None, scope_text="Scope scope", fail_scope=False
    ) -> None:
        self.embedder = FakeEmbedder()
        self.settings = FakeSettings()
        self.repo = FakeRepo()
        self.repo.semantic = semantic or []
        self.repo.keyword = keyword or []
        self._payload = payload
        self._scope_text = scope_text
        self._fail_scope = fail_scope
        self._groq = FakeGroq(payload, scope_text, fail_scope)

    @property
    def groq(self):
        return self._groq


def build_service(
    payload=None, semantic=None, keyword=None, scope_text="Scope scope", fail_scope=False
):
    deps = Dependencies(payload, semantic, keyword, scope_text, fail_scope)
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
    assert len(result.quotes) >= 1


async def test_answer_returns_llm_scope_reply_with_empty_chunks(monkeypatch):
    reply = (
        "I can help with the three expert interviews on robotic surgery - "
        "adoption, barriers, budgets, timelines, or competition."
    )
    svc = build_service(semantic=[], scope_text=reply)
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: svc._deps.groq)
    result = await svc.answer("Random question")
    assert result.answer == svc._deps._scope_text
    assert result.citations == []
    assert result.quotes == []
    assert svc._deps.groq.create_completion_calls == 1


async def test_scope_reply_uses_canned_fallback_when_llm_fails(monkeypatch):
    svc = build_service(semantic=[], fail_scope=True)
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: svc._deps.groq)
    result = await svc.answer("Completely unrelated question")
    assert result.answer == SCOPE_REPLY
    assert result.citations == []
    assert svc._deps.groq.create_completion_calls == 1


async def test_answer_fallback_when_llm_blank(monkeypatch):
    svc = build_service(payload={"answer": "", "citations": []}, semantic=[chunk()])
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: svc._deps.groq)
    result = await svc.answer("q")
    assert result.answer == NO_CONTEXT_FALLBACK
    assert len(result.quotes) == 1


async def test_answer_includes_verbatim_quotes(monkeypatch):
    svc = build_service(
        payload={"answer": "ok", "citations": []},
        semantic=[chunk(content="Exact phrase about budget", distance=0.1)],
        keyword=[chunk(content="Exact phrase about budget", distance=None, chunk_id=1)],
    )
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: svc._deps.groq)
    result = await svc.answer("what about budget approval")
    assert len(result.quotes) == 1
    assert result.quotes[0].quote == "Exact phrase about budget"
    assert result.quotes[0].verification_status == "verified"


async def test_answer_quotes_merge_and_dedupe(monkeypatch):
    svc = build_service(
        payload={"answer": "ok", "citations": []},
        semantic=[
            chunk(content="A", chunk_id=1),
            chunk(content="B", chunk_id=2, distance=0.2),
        ],
        keyword=[chunk(content="A", chunk_id=1)],
    )
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: svc._deps.groq)
    result = await svc.answer("quote something")
    assert len(result.quotes) == 2


async def test_ask_always_returns_answer_with_quotes(monkeypatch):
    svc = build_service(
        payload={"answer": "Training matters", "citations": []},
        semantic=[chunk(content="Isolated training context")],
    )
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: svc._deps.groq)
    result = await svc.ask("give me the exact quote about training")
    assert result.mode == "answer"
    assert "Training matters" in result.answer
    assert len(result.quotes) == 1


async def test_greeting_answered_via_llm(monkeypatch):
    reply = (
        "Hi! I'd love to help you explore the three expert interviews on "
        "the European robotic surgery market."
    )
    svc = build_service(scope_text=reply)
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: svc._deps.groq)
    result = await svc.ask("Hi!")
    assert result.mode == "answer"
    assert result.answer == svc._deps._scope_text
    assert result.citations == []
    assert result.quotes == []
    assert result.answer != NO_CONTEXT_FALLBACK
    assert svc._deps.groq.create_completion_calls == 1


async def test_capability_question_answered_via_llm(monkeypatch):
    reply = (
        "I can only answer about the three expert interviews - try adoption, "
        "barriers, budgets, timelines, or competition."
    )
    svc = build_service(scope_text=reply)
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: svc._deps.groq)
    result = await svc.ask("what can u answer")
    assert result.answer == svc._deps._scope_text
    assert result.citations == []
    assert result.quotes == []
    assert svc._deps.groq.create_completion_calls == 1


def test_detect_off_topic_matches_greetings():
    assert detect_off_topic("Hi there")
    assert detect_off_topic("good morning")
    assert detect_off_topic("thank you!")
    assert detect_off_topic("what can you do?")
    assert detect_off_topic("hello everyone")
    assert detect_off_topic("Is training important?") is False
    assert detect_off_topic("What slows down adoption in Germany?") is False
    assert detect_off_topic("Hi, can you tell me about adoption?") is False