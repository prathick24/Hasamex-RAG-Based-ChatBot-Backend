from pathlib import Path
from unittest import mock

from src.services.theme_service import ThemeService

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATAS = PROJECT_ROOT / "datas"


class FakeEmbedder:
    def embed_one(self, text):
        return [0.1] * 384


class FakeGroq:
    def __init__(self, payload) -> None:
        self._payload = payload
        self.calls = 0

    async def parse_json_completion(self, messages, temperature=0.2, max_tokens=2048, task=None):
        self.calls += 1
        return self._payload


class FakeSettings:
    similarity_threshold = 0.5
    llm_model = "mock"
    cache_llm_results = False
    transcript_dir = str(DATAS)


class FakeRepo:
    def __init__(self, chunks) -> None:
        self._chunks = chunks

    async def similarity_search(self, query_embedding, top_k, transcript_id=None, min_cosine_distance=None):
        return self._chunks


class SimpleNamespace:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


def make_chunk(expert="Dr. X", market="France", content="Training is essential", timestamp="00:10"):
    return type(
        "C",
        (),
        {
            "content": content,
            "timestamp": timestamp,
            "expert_name": expert,
            "market": market,
            "transcript_file": "T.txt",
            "distance": 0.1,
        },
    )()


def make_service(payload, chunks=None) -> tuple[ThemeService, FakeGroq]:
    repo = FakeRepo(chunks or [])
    groq = FakeGroq(payload)
    deps = SimpleNamespace(embedder=FakeEmbedder(), settings=FakeSettings(), groq=groq)
    return ThemeService(repo, deps), groq


async def test_themes_empty_when_no_chunks():
    svc, groq = make_service({})
    entries = await svc.get_themes()
    assert len(entries) == 6
    assert all(entry.themes == [] for entry in entries)
    assert groq.calls == 0


async def test_themes_parsed_and_labeled():
    payload = {
        "topic": "t",
        "themes": [
            {
                "type": "Consensus",
                "summary": "All experts stress training",
                "citations": [
                    {
                        "transcript_file": "T.txt",
                        "expert_name": "Dr. X",
                        "market": "France",
                        "timestamp": "00:10",
                        "quote": "Training is essential",
                    }
                ],
            },
            {"type": "NotReal", "summary": "weird", "citations": []},
        ],
    }
    svc, groq = make_service(payload, chunks=[make_chunk()])
    with mock.patch("src.services.dependencies.get_groq_client", return_value=groq):
        entries = await svc.get_themes()
    assert entries[0].themes[0].type == "Consensus"
    assert entries[0].themes[0].citations[0].quote == "Training is essential"
    assert entries[0].themes[1].type == "Emphasis"
    assert groq.calls == 6


async def test_themes_citations_verified_against_chunks():
    payload = {
        "topic": "t",
        "themes": [
            {
                "type": "Disagreement",
                "summary": "Timelines differ",
                "citations": [
                    {
                        "transcript_file": "T.txt",
                        "expert_name": "Dr. X",
                        "market": "France",
                        "timestamp": "00:10",
                        "quote": "fabricated text",
                    }
                ],
            }
        ],
    }
    svc, groq = make_service(payload, chunks=[make_chunk(content="Real content here")])
    with mock.patch("src.services.dependencies.get_groq_client", return_value=groq):
        entries = await svc.get_themes()
    assert entries[0].themes[0].type == "Disagreement"
    assert entries[0].themes[0].citations == []


async def test_themes_skips_non_dict_items():
    payload = {
        "topic": "t",
        "themes": [
            "just a string",
            42,
            {
                "type": "Consensus",
                "summary": "Training matters",
                "citations": ["also badly shaped"],
            },
        ],
    }
    svc, groq = make_service(payload, chunks=[make_chunk(content="Isolated cache context")])
    with mock.patch("src.services.dependencies.get_groq_client", return_value=groq):
        entries = await svc.get_themes()
    themes = entries[0].themes
    assert len(themes) == 1
    assert themes[0].type == "Consensus"
    assert themes[0].summary == "Training matters"
    assert themes[0].citations == []


async def test_themes_yields_empty_entry_on_topic_error():
    svc, groq = make_service({}, chunks=[make_chunk()])

    async def boom(topic):
        raise RuntimeError("boom")

    svc._analyze_topic = boom

    with mock.patch("src.services.dependencies.get_groq_client", return_value=groq):
        events = [e async for e in svc.generate_themes()]
    topics = [e for e in events if e["type"] == "topic"]
    assert len(topics) == 6
    assert all(e["themes"] == [] for e in topics)
    assert all(e["error"] is True for e in topics)
    assert events[-1]["type"] == "done"


async def test_themes_success_entries_not_flagged_as_error():
    payload = {
        "topic": "t",
        "themes": [
            {
                "type": "Consensus",
                "summary": "All experts stress training",
                "citations": [],
            }
        ],
    }
    svc, groq = make_service(payload, chunks=[make_chunk(content="Isolated success context")])
    with mock.patch("src.services.dependencies.get_groq_client", return_value=groq):
        entries = await svc.get_themes()
    assert all(len(entry.themes) == 1 for entry in entries)
    assert all(entry.error is False for entry in entries)