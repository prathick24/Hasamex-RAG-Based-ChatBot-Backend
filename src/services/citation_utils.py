import logging
import re

from src.repositories.schema.schemas import Citation
from src.utils.exceptions.exceptions import LLMError

logger = logging.getLogger("hasamex.citations")

# Fold common typographic variants onto ASCII so near-exact quotes still verify
# (em/en dashes, curly quotes, narrow/no-break spaces) without weakening the
# substring guarantee: after folding, matching is still exact.
_UNICODE_FOLD = str.maketrans(
    {
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
        "\u2014": "-", "\u2015": "-",
        "\u00a0": " ", "\u2009": " ", "\u200a": " ", "\u202f": " ",
    }
)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_match(text: str) -> str:
    """Whitespace-compact + typographic-fold + lowercase, for comparison only."""
    return normalize_whitespace(str(text).translate(_UNICODE_FOLD)).lower()


def is_quote_in_content(quote: str, content: str) -> bool:
    """Check a quote is a verifiable substring of the source content."""
    return normalize_for_match(quote) in normalize_for_match(content)


def _names_match(requested: str, chunk_expert: str) -> bool:
    return normalize_for_match(requested) in normalize_for_match(chunk_expert)


def _find_matching_chunk(citation: dict, available_chunks: list[dict]) -> dict | None:
    """Locate the source chunk backing a citation.

    Prefers a chunk whose expert matches the citation AND contains the quote;
    falls back to any chunk containing the quote; otherwise the first
    expert-matched chunk (so citation metadata still derives from real data).
    """
    requested_name = str(citation.get("expert_name", "")).strip()
    quote = str(citation.get("quote", "")).strip()

    name_candidates: list[dict] = []
    for chunk in available_chunks:
        if _names_match(requested_name, chunk["expert_name"]):
            if quote and is_quote_in_content(quote, chunk["content"]):
                return chunk
            name_candidates.append(chunk)

    if quote:
        for chunk in available_chunks:
            if is_quote_in_content(quote, chunk["content"]):
                return chunk

    return name_candidates[0] if name_candidates else None


def verify_citations(
    citations: list[dict], available_chunks: list[dict]
) -> tuple[list[Citation], list[dict]]:
    """Verify citation quotes are exact substrings of available chunk content.

    available_chunks: list of dicts with keys content, expert_name, market,
    timestamp, transcript_file. Verified citations inherit ALL metadata
    (transcript_file, expert_name, market, timestamp) from the matched chunk, so
    displayed sources always come from the corpus, never from model-hallucinated
    filenames. Returns (verified citations, dropped citations).
    """
    verified: list[Citation] = []
    dropped: list[dict] = []

    for citation in citations:
        quote = str(citation.get("quote", "")).strip()
        if not quote:
            logger.warning(
                "dropped citation: empty quote (expert=%r)", citation.get("expert_name")
            )
            dropped.append(citation)
            continue

        chunk = _find_matching_chunk(citation, available_chunks)
        if chunk is not None and is_quote_in_content(quote, chunk["content"]):
            verified.append(
                Citation(
                    transcript_file=str(chunk["transcript_file"]),
                    expert_name=str(chunk["expert_name"]),
                    market=str(chunk["market"]),
                    timestamp=str(chunk["timestamp"] or citation.get("timestamp", "")),
                    quote=normalize_whitespace(quote),
                )
            )
        else:
            logger.warning(
                "dropped citation: quote not found in any retrieved chunk "
                "(quote=%r, expert=%r)",
                quote,
                citation.get("expert_name"),
            )
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
    """Serialize retrieved chunks into a context block: timestamp + expert + file + content."""
    parts = []
    for chunk in chunks:
        parts.append(
            f"[{chunk.timestamp}] [{chunk.expert_name} ({chunk.market})] "
            f"[{chunk.transcript_file}]\n{chunk.content}"
        )
    return "\n\n".join(parts)


def require_llm_result(content: str) -> str:
    if not content:
        raise LLMError("Empty response from language model")
    return content
