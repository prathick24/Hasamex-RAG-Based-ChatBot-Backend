import logging
import re

from src.prompt import build_qa_answer_messages, build_scope_messages
from src.repositories.schema.response import SimilarChunk
from src.repositories.schema.schemas import AnswerModeResponse, QuoteResponseItem
from src.repositories.transcript_repository import TranscriptRepository
from src.services.cache import acached_result, make_cache_key
from src.services.citation_utils import (
    build_citation_context,
    chunk_to_dict,
    verify_citations,
)
from src.settings import Settings
from src.utils.exceptions.exceptions import ApplicationError

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


def detect_off_topic(question: str) -> bool:
    """Detect pure greetings / pleasantries / capability questions addressed to the bot."""
    return bool(SCOPE_CHITCHAT.search(question))


class QAService:
    def __init__(self, repository: TranscriptRepository, dependencies) -> None:
        self._repository = repository
        self._deps = dependencies
        self._settings: Settings = dependencies.settings

    async def _collect_quotes(self, question: str, top_k: int) -> list[QuoteResponseItem]:
        query_embedding = self._deps.embedder.embed_one(question)
        semantic_chunks = await self._repository.similarity_search(
            query_embedding=query_embedding,
            top_k=top_k,
            min_cosine_distance=self._settings.similarity_threshold,
        )
        keyword_chunks = await self._repository.keyword_search(question, top_k=top_k)

        merged: dict[int, SimilarChunk] = {}
        for chunk in semantic_chunks:
            merged[chunk.chunk_id] = chunk
        for chunk in keyword_chunks:
            merged.setdefault(chunk.chunk_id, chunk)

        return [
            QuoteResponseItem(
                quote=chunk.content,
                transcript_file=chunk.transcript_file,
                expert_name=chunk.expert_name,
                market=chunk.market,
                timestamp=chunk.timestamp,
                verification_status="verified",
            )
            for chunk in merged.values()
        ]

    async def _scope_answer(self, question: str) -> str:
        """LLM-generated conversational reply for greetings and out-of-scope
        questions, guided by a role prompt. Falls back to the canned scope
        message when the LLM is unavailable. Cached per question (no context).
        """
        cache_key = make_cache_key("qa_scope", self._settings.llm_model, question)

        async def _produce() -> str:
            from src.services.dependencies import get_groq_client

            try:
                groq = get_groq_client()
                messages = build_scope_messages(question=question)
                completion = await groq.create_completion(
                    messages, temperature=0.7, max_tokens=200, task="qa_scope"
                )
            except ApplicationError:
                logger.warning("scope_reply_llm_failed", exc_info=True)
                return SCOPE_REPLY
            content = (completion.get("content") or "").strip()
            return content or SCOPE_REPLY

        return await acached_result(cache_key, _produce)

    async def answer(self, question: str, top_k: int | None = None) -> AnswerModeResponse:
        k = top_k or self._settings.top_k
        quotes = await self._collect_quotes(question, k)

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
                answer=await self._scope_answer(question),
                citations=[],
                quotes=quotes,
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
            quotes=quotes,
        )

    async def ask(self, question: str, top_k: int | None = None) -> AnswerModeResponse:
        if detect_off_topic(question):
            return AnswerModeResponse(
                question=question,
                mode="answer",
                answer=await self._scope_answer(question),
                citations=[],
                quotes=[],
            )
        return await self.answer(question, top_k)
