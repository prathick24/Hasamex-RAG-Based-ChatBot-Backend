import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.settings import Settings  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def make_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        groq_api_key="test-key",
        groq_base_url="https://api.groq.com/openai/v1",
        llm_model="llama-3.3-70b-versatile",
        embedding_model="fake-local-model",
        embedding_dimensions=384,
        top_k=5,
        similarity_threshold=0.5,
        transcript_dir=str(PROJECT_ROOT / "datas"),
        log_level="INFO",
        cache_llm_results=False,
    )


@pytest.fixture
def settings() -> Settings:
    return make_settings()


class FakeEmbedder:
    """Deterministic fake embedder returning fixed-dimension unit-ish vectors."""

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * self.dimension for _ in texts]

    def embed_one(self, text: str) -> list[float]:
        return [0.01] * self.dimension


class FakeGroq:
    """Fake Groq client returning a scripted JSON payload per call."""

    def __init__(self, payloads: list[dict] | None = None) -> None:
        self.payloads = payloads or []
        self.calls: list[list[dict]] = []

    def set_default(self, payload: dict) -> None:
        self.payloads = [payload]

    async def parse_json_completion(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 2048, task: str | None = None) -> dict:
        self.calls.append(messages)
        if not self.payloads:
            return {"answer": "mock answer", "citations": []}
        return self.payloads.pop(0)