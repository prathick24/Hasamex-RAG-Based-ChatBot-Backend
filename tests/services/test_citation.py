from src.services.citation_utils import (
    build_citation_context,
    chunk_to_dict,
    is_quote_in_content,
    normalize_whitespace,
    verify_citations,
)


class FakeChunk:
    def __init__(self, content="content", expert_name="Dr. X", timestamp="00:10",
                 transcript_file="T.txt", market="France") -> None:
        self.content = content
        self.expert_name = expert_name
        self.timestamp = timestamp
        self.transcript_file = transcript_file
        self.market = market


def test_normalize_whitespace():
    assert normalize_whitespace("  a\n b\t c  ") == "a b c"


def test_is_quote_in_content_exact():
    assert is_quote_in_content("Doom 2 was great", "Doom 2   was   great")


def test_is_quote_in_content_not_found():
    assert not is_quote_in_content("missing phrase", "some other content")


def test_build_citation_context():
    context = build_citation_context([FakeChunk(content="hello world")])
    assert "00:10" in context
    assert "Dr. X" in context
    assert "hello world" in context


def test_chunk_to_dict():
    result = chunk_to_dict(FakeChunk())
    assert result["content"] == "content"
    assert result["expert_name"] == "Dr. X"


def test_verify_citations_verified():
    chunk = FakeChunk(content="The price is high and training matters")
    citations, dropped = verify_citations(
        [
            {
                "transcript_file": "T.txt",
                "expert_name": "Dr. X",
                "market": "France",
                "timestamp": "00:10",
                "quote": "training matters",
            }
        ],
        [chunk_to_dict(chunk)],
    )
    assert len(citations) == 1
    assert citations[0].quote == "training matters"
    assert dropped == []


def test_verify_citations_fabricated_quote_dropped():
    chunk = FakeChunk(content="The price is high")
    citations, dropped = verify_citations(
        [
            {
                "transcript_file": "T.txt",
                "expert_name": "Dr. X",
                "market": "France",
                "timestamp": "00:10",
                "quote": "totally invented",
            }
        ],
        [chunk_to_dict(chunk)],
    )
    assert citations == []
    assert len(dropped) == 1


def test_verify_citations_empty_quote_dropped():
    citations, dropped = verify_citations(
        [{"timestamp": "00:01", "quote": "", "expert_name": "", "transcript_file": "", "market": ""}],
        [],
    )
    assert citations == []
    assert len(dropped) == 1


def test_verify_citations_cross_expert_fallback():
    chunk = FakeChunk(content="Budget approvals take forever", expert_name="Anna Keller")
    citations, dropped = verify_citations(
        [
            {
                "transcript_file": "T.txt",
                "expert_name": "Anna Keller",
                "market": "Germany",
                "timestamp": "02:08",
                "quote": "Budget approvals",
            }
        ],
        [chunk_to_dict(chunk)],
    )
    assert len(citations) == 1
    assert dropped == []


def test_verify_citations_replaces_fabricated_filename_with_real_chunk_metadata():
    chunk = FakeChunk(
        content="Training matters, especially in the first year.",
        expert_name="Dr. Jean Martin",
        transcript_file="Transcript_1_France.txt",
        market="France",
        timestamp="03:10",
    )
    citations, dropped = verify_citations(
        [
            {
                "transcript_file": "interview.txt",
                "expert_name": "Dr. Jean Martin",
                "market": "France",
                "timestamp": "03:10",
                "quote": "Training matters, especially in the first year.",
            }
        ],
        [chunk_to_dict(chunk)],
    )
    assert len(citations) == 1
    assert dropped == []
    assert citations[0].transcript_file == "Transcript_1_France.txt"
    assert citations[0].expert_name == "Dr. Jean Martin"
    assert citations[0].market == "France"
    assert citations[0].timestamp == "03:10"


def test_is_quote_in_content_folds_typographic_variants():
    assert is_quote_in_content("costs around 15\u201320 percent", "costs around 15-20 percent")
    assert is_quote_in_content("he said \u2018training matters\u2019", "he said 'training matters'")
    assert is_quote_in_content("costs\u00a015 percent", "costs 15 percent")