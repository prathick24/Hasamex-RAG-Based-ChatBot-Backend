import re
from pathlib import Path

from src.services.interview_guide_service import InterviewGuideService

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATAS = PROJECT_ROOT / "datas"


class FakeEmbedder:
    def embed_one(self, text):
        return [0.1] * 384


class FakeGroq:
    def __init__(self, answer, citation=None) -> None:
        self._answer = answer
        self._citation = citation
        self.calls = 0

    async def parse_json_completion(self, messages, temperature=0.2, max_tokens=2048, task=None):
        self.calls += 1
        user = messages[1]["content"]
        qids = [int(qid) for qid in re.findall(r"Q(\d+):", user)]
        answers = []
        for qid in qids:
            citation = dict(self._citation) if self._citation else None
            answers.append(
                {
                    "question_id": qid,
                    "expert": "Dr. X",
                    "answer": self._answer,
                    "citations": [citation] if citation else [],
                }
            )
        return {"answers": answers}


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
            {
                "id": transcript_id,
                "expert_name": "Dr. X",
                "filename": "T.txt",
                "market": "France",
                "version": 1,
            },
        )()

    async def similarity_search(
        self, query_embedding, top_k, transcript_id=None, min_cosine_distance=None
    ):
        return self._chunks

    async def question_search(
        self, query_embedding, top_k, transcript_id=None, min_cosine_distance=None
    ):
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


def make_service(answer, chunks=None, citation=None):
    repo = FakeRepo([make_transcript_record()], chunks or [])
    groq = FakeGroq(answer, citation=citation)
    deps = SimpleNamespace(embedder=FakeEmbedder(), settings=FakeSettings(), groq=groq)
    return InterviewGuideService(repo, deps), groq


class SimpleNamespace:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


async def collect_entries(svc) -> list[dict]:
    questions: list[dict] = []
    answers_by_q: dict[int, list[dict]] = {}
    async for event in svc.generate_interview_guide():
        if event["type"] == "meta":
            questions = event["questions"]
        elif event["type"] == "batch":
            for answer in event["answers"]:
                answers_by_q.setdefault(answer["question_id"], []).append(answer)
    return [
        {
            "question_id": question["question_id"],
            "question": question["question"],
            "answers": answers_by_q.get(question["question_id"], []),
        }
        for question in questions
    ]


async def test_interview_guide_generates_answers(monkeypatch):
    chunk = make_chunk(content="Adoption is concentrated in academic hospitals and private centres")
    citation = {
        "transcript_file": "T.txt",
        "expert_name": "Dr. X",
        "market": "France",
        "timestamp": "00:10",
        "quote": "concentrated in academic hospitals",
    }
    svc, groq = make_service(
        "Adoption is concentrated in academic hospitals.", chunks=[chunk], citation=citation
    )
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: groq)

    entries = await collect_entries(svc)
    assert len(entries) == 6
    assert entries[0]["question_id"] == 1
    answer = entries[0]["answers"][0]
    assert "Adoption is concentrated" in answer["answer"]
    assert len(answer["citations"]) == 1
    assert answer["citations"][0]["quote"] == "concentrated in academic hospitals"
    assert groq.calls == 2  # 6 questions batched by 3


async def test_interview_guide_not_mentioned_when_no_chunks(monkeypatch):
    svc, groq = make_service("unused", chunks=[])
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: groq)

    entries = await collect_entries(svc)
    for entry in entries:
        assert entry["answers"][0]["answer"] == "Not mentioned in this transcript"
        assert entry["answers"][0]["citations"] == []
    assert groq.calls == 0


async def test_interview_guide_fabricated_citations_dropped(monkeypatch):
    svc, groq = make_service(
        "something",
        chunks=[make_chunk()],
        citation={
            "transcript_file": "T.txt",
            "expert_name": "Dr. X",
            "market": "France",
            "timestamp": "00:10",
            "quote": "not in the source at all",
        },
    )
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: groq)

    entries = await collect_entries(svc)
    assert entries[0]["answers"][0]["citations"] == []


async def test_guide_skips_non_dict_answers(monkeypatch):
    svc, _ = make_service("unused", chunks=[make_chunk(content="Isolated cache context")])

    class Malformed:
        calls = 0

        async def parse_json_completion(
            self, messages, temperature=0.2, max_tokens=2048, task=None
        ):
            self.calls += 1
            return {
                "answers": [
                    "oops",
                    42,
                    {"question_id": 2, "answer": "valid answer text", "citations": []},
                ]
            }

    malformed = Malformed()
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: malformed)

    entries = await collect_entries(svc)
    assert entries[0]["answers"][0]["answer"] == "Not mentioned in this transcript"
    assert "valid answer text" in entries[1]["answers"][0]["answer"]
    assert malformed.calls == 2  # 6 questions → 2 batches of 3


async def test_guide_yields_fallback_answers_on_batch_error(monkeypatch):
    svc, groq = make_service("x", chunks=[make_chunk()])
    monkeypatch.setattr("src.services.dependencies.get_groq_client", lambda: groq)

    async def boom(transcript, items):
        raise RuntimeError("groq down")

    svc._answer_expert_batch = boom

    events = [e async for e in svc.generate_interview_guide()]
    batches = [e for e in events if e["type"] == "batch"]
    assert len(batches) == 2
    assert all("snag" in a["answer"] for b in batches for a in b["answers"])
    assert events[-1]["type"] == "done"
