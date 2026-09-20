from pathlib import Path

import pytest

from src.utils.exceptions.exceptions import ValidationError
from src.utils.parser import load_interview_guide, parse_transcript_file, parse_transcript_text

DATAS = Path(__file__).resolve().parent.parent.parent / "datas"


def test_parse_france():
    parsed = parse_transcript_file(DATAS / "Transcript_1_France.txt")
    assert parsed.expert_name == "Dr. Jean Martin"
    assert parsed.expert_role == "Head of Urology"
    assert parsed.market == "France"
    assert parsed.filename == "Transcript_1_France.txt"
    expert_turns = [t for t in parsed.turns if t.speaker == "Expert"]
    assert len(expert_turns) == 7
    assert expert_turns[0].speaker_index == "EX_00"
    assert expert_turns[0].timestamp == "00:18"
    assert "capital budget approval" in expert_turns[1].content
    interviewer_turns = [t for t in parsed.turns if t.speaker == "Interviewer"]
    assert interviewer_turns[0].speaker_index == "IN_00"


def test_parse_germany():
    parsed = parse_transcript_file(DATAS / "Transcript_2_Germany.txt")
    assert parsed.expert_name == "Anna Keller"
    assert parsed.market == "Germany"
    expert_turns = [t for t in parsed.turns if t.speaker == "Expert"]
    assert len(expert_turns) == 7
    assert any("Nine to eighteen months" in t.content for t in expert_turns)


def test_parse_uk():
    parsed = parse_transcript_file(DATAS / "Transcript_3_UK.txt")
    assert parsed.expert_name == "Dr. Emily Carter"
    assert parsed.market == "United Kingdom"
    expert_turns = [t for t in parsed.turns if t.speaker == "Expert"]
    assert len(expert_turns) == 7


def test_parse_timestamps_preserved_verbatim():
    parsed = parse_transcript_file(DATAS / "Transcript_1_France.txt")
    timestamps = [t.timestamp for t in parsed.turns if t.speaker == "Expert"]
    assert timestamps == ["00:18", "01:20", "02:18", "03:10", "04:08", "05:07", "06:08"]


def test_parse_missing_file_raises():
    with pytest.raises(ValidationError):
        parse_transcript_file(DATAS / "Missing_File.txt")


def test_parse_bad_header_raises(tmp_path):
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text(
        "No metadata header here\n\n00:00\nInterviewer: hi\n00:05\nExpert: hello\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        parse_transcript_file(bad_file)


def test_parse_no_turns_raises(tmp_path):
    bad_file = tmp_path / "empty.txt"
    bad_file.write_text(
        "Expert 1 \u2013 Dr. X\nRole: Surgeon\nMarket: X\n\nSome prose without timestamps.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        parse_transcript_file(bad_file)


def test_parse_transcript_text_matches_file_parse():
    content = (DATAS / "Transcript_1_France.txt").read_text(encoding="utf-8", errors="replace")
    parsed = parse_transcript_text("Transcript_1_France.txt", content)
    assert parsed.expert_name == "Dr. Jean Martin"
    assert parsed.expert_role == "Head of Urology"
    assert parsed.market == "France"
    assert parsed.filename == "Transcript_1_France.txt"
    expert_turns = [t for t in parsed.turns if t.speaker == "Expert"]
    assert len(expert_turns) == 7
    assert expert_turns[0].speaker_index == "EX_00"


def test_load_interview_guide():
    questions = load_interview_guide(DATAS / "Interview_Guide.txt")
    assert len(questions) == 6
    assert "adoption" in questions[0].lower()
    assert "timeline" in questions[5].lower()


def test_load_interview_guide_missing_raises(tmp_path):
    with pytest.raises(ValidationError):
        load_interview_guide(tmp_path / "nope.txt")