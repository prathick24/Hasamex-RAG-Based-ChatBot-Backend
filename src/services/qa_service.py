import logging
import re

from src.prompt import build_qa_answer_messages
from src.repositories.schema.response import SimilarChunk
from src.repositories.schema.schemas import (
    AnswerModeResponse,
    QuoteModeResponse,
    QuoteResponseItem,
)
from src.repositories.transcript_repository import TranscriptRepository
from src.services.cache import acached_result, make_cache_key
from src.services.citation_utils import (
    build_citation_context,
    chunk_to_dict,
    verify_citations,
)
from src.settings import Settings

logger = logging.getLogger("hasamex.qa")

NO_CONTEXT_FALLBACK = (
    "I couldn't find anything in these transcripts that answers that. "
    "I only cover the three expert interviews on the European robotic surgery market "
    "- try asking about adoption, barriers, budgets, timelines, or competition."
)

SCOPE_REPLY = (
    "Hi! I can only answer questions about these three expert-call transcripts "
    "(European robotic surgery market). Try asking me about adoption, barriers, "
    "budgets, timelines, or exact quotes from the experts."
)

SCOPE_CHITCHAT = re.compile(
    r"^\s*(?:(?:hi|hello|hey|howdy|hiya)\b"
    r"|(?:good (?:morning|afternoon|evening))\b"
    r"|(?:thanks|thank you|thx)\b"
    r"|(?:how are you|how's it going|what's up)\b"
    r"|(?:what can you do|what do you do|who are you|what are you)\b"
    r"|(?:bye|goodbye|see you)\b)"
    r"(?:[\s,.!?;:]+(?:there|guys|everyone|u|you|all|a lot|very much)?)*"
    r"[\s,.!?;:]*$",
    re.IGNORECASE,
)

QUOTE_INTENT_SUBSTRINGS = (
    "exact quote",
    "exact words",
    "exact wording",
    "verbatim",
    "word for word",
    "direct quote",
    "quote exactly",
    "quote the line",
    "quote what",
    "give me the quote",
    "paste the quote",
    "show the quote",
    "please quote",
)

QUOTE_INTENT_REGEX = (r"what did .+ say (exactly|verbatim)",)


def detect_quote_intent(question: str) -> bool:
    """Auto-detect a quote request from the question phrasing (FR-003)."""
    lowered = question.lower()
    if any(substring in lowered for substring in QUOTE_INTENT_SUBSTRINGS):
        return True
    return any(re.search(pattern, question, re.IGNORECASE) for pattern in QUOTE_INTENT_REGEX)


def detect_off_topic(question: str) -> bool:
    """Detect pure greetings / pleasantries / capability questions addressed to the bot."""
    return bool(SCOPE_CHITCHAT.search(question))


class QAService:
    def __init__(self, repository: TranscriptRepository, dependencies) -> None:
        self._repository = repository
        self._deps = dependencies
        self._settings: Settings = dependencies.settings

    async def answer(self, question: str, top_k: int | None = None) -> AnswerModeResponse:
        k = top_k or self._settings.top_k
        query_embedding = self._deps.embedder.embed_one(question)
        chunks = await self._repository.similarity_search(
            query_embedding=query_embedding,
            top_k=k,
            min_cosine_distance=self._settings.similarity_threshold,
        )

        if not chunks:
            return AnswerModeResponse(
                question=question,
                mode="answer",
                answer=NO_CONTEXT_FALLBACK,
                citations=[],
            )

        context = build_citation_context(chunks)
        cache_key = make_cache_key("qa_answer", self._settings.llm_model, question, context)

        async def _produce() -> dict:
            from src.services.dependencies import get_groq_client

            groq = get_groq_client()
            messages = build_qa_answer_messages(question=question, context=context)
            return await groq.parse_json_completion(messages, temperature=0.2, task="qa_answer")

        payload = await acached_result(cache_key, _produce)

        available = [chunk_to_dict(chunk) for chunk in chunks]
        citations, _ = verify_citations(payload.get("citations", []), available)

        answer = str(payload.get("answer", "")).strip()
        if not answer:
            answer = NO_CONTEXT_FALLBACK

        return AnswerModeResponse(
            question=question,
            mode="answer",
            answer=answer,
            citations=citations,
        )

    async def quote(self, question: str, top_k: int | None = None) -> QuoteModeResponse:
        k = top_k or self._settings.top_k
        query_embedding = self._deps.embedder.embed_one(question)
        semantic_chunks = await self._repository.similarity_search(
            query_embedding=query_embedding,
            top_k=k,
            min_cosine_distance=self._settings.similarity_threshold,
        )
        keyword_chunks = await self._repository.keyword_search(question, top_k=k)

        merged: dict[int, SimilarChunk] = {}
        for chunk in semantic_chunks:
            merged[chunk.chunk_id] = chunk
        for chunk in keyword_chunks:
            merged.setdefault(chunk.chunk_id, chunk)

        quotes: list[QuoteResponseItem] = []
        for chunk in merged.values():
            status = "verified"
            if chunk.distance is None:
                status = "verified"
            quotes.append(
                QuoteResponseItem(
                    quote=chunk.content,
                    transcript_file=chunk.transcript_file,
                    expert_name=chunk.expert_name,
                    market=chunk.market,
                    timestamp=chunk.timestamp,
                    verification_status=status,
                )
            )

        if not quotes:
            return QuoteModeResponse(
                question=question,
                mode="quote",
                answer="No exact quote found in the available transcripts.",
                quotes=[],
                citations=[],
            )

        citations, _ = verify_citations(
            [
                {
                    "transcript_file": q.transcript_file,
                    "expert_name": q.expert_name,
                    "market": q.market,
                    "timestamp": q.timestamp,
                    "quote": q.quote,
                }
                for q in quotes
            ],
            [chunk_to_dict(chunk) for chunk in merged.values()],
        )

        return QuoteModeResponse(
            question=question,
            mode="quote",
            answer=None,
            quotes=quotes,
            citations=citations,
        )

    async def ask(self, question: str, mode: str | None = None, top_k: int | None = None):
        if detect_off_topic(question):
            return AnswerModeResponse(
                question=question,
                mode="answer",
                answer=SCOPE_REPLY,
                citations=[],
            )
        resolved_mode = mode or ("quote" if detect_quote_intent(question) else "answer")
        if resolved_mode == "quote":
            return await self.quote(question, top_k)
        return await self.answer(question, top_k)
