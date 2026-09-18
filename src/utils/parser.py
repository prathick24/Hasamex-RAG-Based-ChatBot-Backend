import re
from pathlib import Path

from src.repositories.schema.response import ParsedTranscript, ParsedTurn
from src.utils.exceptions.exceptions import ValidationError

TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}$")
SPEAKER_LABEL_RE = re.compile(r"^([^:]{2,60}):\s*(.*)$")
HEADER_EXPERT_RE = re.compile(r"^Expert\s+\d+\s*[\u2013-]\s*(.+)$", re.IGNORECASE)
HEADER_ROLE_RE = re.compile(r"^Role\s*:\s*(.+)$", re.IGNORECASE)
HEADER_MARKET_RE = re.compile(r"^Market\s*:\s*(.+)$", re.IGNORECASE)

EXCLUDED_GUIDE_LINES = ("interview guide", "project objective")


def _split_speaker_label(text: str) -> tuple[str, str] | None:
    """Split 'Label: content' into (label, content). None when there is no label."""
    match = SPEAKER_LABEL_RE.match(text)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _classify_speaker(label: str) -> str:
    if label.lower().startswith("interviewer"):
        return "Interviewer"
    return "Expert"


def _parse_header(raw_lines: list[str]) -> tuple[str, str | None, str]:
    expert_name: str | None = None
    expert_role: str | None = None
    market: str | None = None

    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue

        expert_match = HEADER_EXPERT_RE.match(stripped)
        if expert_match:
            expert_name = expert_match.group(1).strip()
            continue

        role_match = HEADER_ROLE_RE.match(stripped)
        if role_match:
            expert_role = role_match.group(1).strip()
            continue

        market_match = HEADER_MARKET_RE.match(stripped)
        if market_match:
            market = market_match.group(1).strip()
            continue

        split = _split_speaker_label(stripped)
        if split and not TIMESTAMP_RE.match(stripped):
            break

    if not expert_name or not market:
        raise ValidationError(
            "Could not parse expert metadata from header. "
            "Expected 'Expert N \u2013 Name', 'Role: ...', 'Market: ...'."
        )
    return expert_name, expert_role, market


def parse_transcript_file(filepath: Path) -> ParsedTranscript:
    """Parse a transcript file into a ParsedTranscript with ordered turns."""
    if not filepath.exists():
        raise ValidationError(f"Transcript file not found: {filepath.name}")

    raw_lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
    expert_name, expert_role, market = _parse_header(raw_lines)

    turns: list[ParsedTurn] = []
    current_timestamp: str | None = None
    current_speaker: str | None = None
    current_content: list[str] = []

    def _flush_turn() -> None:
        nonlocal current_timestamp, current_speaker
        content = " ".join(part for part in current_content if part).strip()
        if current_timestamp and current_speaker and content:
            turns.append(
                ParsedTurn(
                    speaker=_classify_speaker(current_speaker),
                    speaker_index="",
                    timestamp=current_timestamp,
                    content=content,
                )
            )
        current_content.clear()

    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue

        if TIMESTAMP_RE.match(stripped):
            _flush_turn()
            current_timestamp = stripped
            continue

        split = _split_speaker_label(stripped)
        if split:
            label, content = split
            _flush_turn()
            current_speaker = label
            current_content.append(content)
            continue

        if current_speaker is not None:
            current_content.append(stripped)

    _flush_turn()

    if not turns:
        raise ValidationError(f"No timestamped turns found in {filepath.name}")

    interview_count = 0
    expert_count = 0
    for turn in turns:
        if turn.speaker == "Interviewer":
            turn.speaker_index = f"IN_{interview_count:02d}"
            interview_count += 1
        else:
            turn.speaker_index = f"EX_{expert_count:02d}"
            expert_count += 1

    return ParsedTranscript(
        filename=filepath.name,
        expert_name=expert_name,
        expert_role=expert_role,
        market=market,
        turns=turns,
    )


def load_interview_guide(filepath: Path) -> list[str]:
    """Extract the numbered interview-guide questions from the guide file."""
    if not filepath.exists():
        raise ValidationError(f"Interview guide file not found: {filepath.name}")

    questions: list[str] = []
    lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(token in stripped.lower() for token in EXCLUDED_GUIDE_LINES):
            continue
        match = re.match(r"^\d{1,2}\.\s*(.+)$", stripped)
        if match:
            questions.append(match.group(1).strip())

    return questions
