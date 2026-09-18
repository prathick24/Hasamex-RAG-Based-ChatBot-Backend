import re

from src.repositories.schema.schemas import Citation
from src.utils.exceptions.exceptions import LLMError


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_quote_in_content(quote: str, content: str) -> bool:
    """Check a quote is a verifiable substring of the source content."""
    return normalize_whitespace(quote).lower() in normalize_whitespace(content).lower()


def _find_source_content(citations_chunk, available_chunks) -> str | None:
    """Best-effort match of a citation to the available chunk list."""
    for chunk in available_chunks:
        name_match = (
            not citations_chunk.get("expert_name")
            or normalize_whitespace(str(citations_chunk.get("expert_name"))).lower()
            in normalize_whitespace(chunk["expert_name"]).lower()
        )
        if name_match:
            return chunk["content"]
    # fallback: any chunk containing the quote
    quote = str(citations_chunk.get("quote", "")).strip()
    for chunk in available_chunks:
        if quote and is_quote_in_content(quote, chunk["content"]):
            return chunk["content"]
    return None


def verify_citations(
    citations: list[dict], available_chunks: list[dict]
) -> tuple[list[Citation], list[dict]]:
    """Verify citation quotes are exact substrings of available chunk content.

    available_chunks: list of dicts with keys content, expert_name (and optionally timestamp).
    Returns (verified citations, dropped citations).
    """
    verified: list[Citation] = []
    dropped: list[dict] = []

    for citation in citations:
        timestamp = str(citation.get("timestamp", "")).strip()
        quote = str(citation.get("quote", "")).strip()
        if not quote:
            dropped.append(citation)
            continue

        content = _find_source_content(citation, available_chunks)
        if content is not None and is_quote_in_content(quote, content):
            verified.append(
                Citation(
                    transcript_file=str(citation.get("transcript_file", "")),
                    expert_name=str(citation.get("expert_name", "")),
                    market=str(citation.get("market", "")),
                    timestamp=timestamp,
                    quote=normalize_whitespace(quote),
                )
            )
        else:
            dropped.append(citation)

    return verified, dropped


def chunk_to_dict(chunk) -> dict:
    return {
        "content": chunk.content,
        "expert_name": chunk.expert_name,
        "timestamp": chunk.timestamp,
        "transcript_file": chunk.transcript_file,
        "market": chunk.market,
    }


def build_citation_context(chunks) -> str:
    """Serialize retrieved chunks into a context block: timestamp + expert + content."""
    parts = []
    for chunk in chunks:
        parts.append(f"[{chunk.timestamp}] [{chunk.expert_name} ({chunk.market})]\n{chunk.content}")
    return "\n\n".join(parts)


def require_llm_result(content: str) -> str:
    if not content:
        raise LLMError("Empty response from language model")
    return content
