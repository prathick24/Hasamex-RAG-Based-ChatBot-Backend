import logging
from pathlib import Path

from src.prompt import build_themes_messages
from src.repositories.schema.schemas import ChunkWithTranscript, Theme, ThemeEntry
from src.repositories.transcript_repository import TranscriptRepository
from src.services import audit_service
from src.services.cache import acached_result, make_cache_key
from src.services.citation_utils import (
    build_citation_context,
    chunk_to_dict,
    verify_citations,
)
from src.settings import Settings
from src.utils.parser import load_interview_guide

logger = logging.getLogger("hasamex.themes")

THEME_EXPERT_TOP_K = 6


class ThemeService:
    def __init__(self, repository: TranscriptRepository, dependencies) -> None:
        self._repository = repository
        self._deps = dependencies
        self._settings: Settings = dependencies.settings

    async def _retrieve_topic_chunks(self, topic: str) -> list[ChunkWithTranscript]:
        """Per-expert retrieval: the top-K chunks scoped to each expert's
        transcript (no distance cutoff), then merged by chunk id.

        A single global top-K can silently drop a topic's chunks from one or
        more experts. On the real corpus the purchase-timeline topic ranked each
        expert's timeline chunk as low as 6th against the roundabout guide
        sentence, so the guarantee is top-6 per expert (bounded context, worst
        case 3 experts x 6). Relevance filtering is left to the LLM's RULE-204.
        """
        query_embedding = self._deps.embedder.embed_one(topic)
        transcripts = await self._repository.list_transcripts()
        merged: dict[int, ChunkWithTranscript] = {}
        for transcript in transcripts:
            chunks = await self._repository.similarity_search(
                query_embedding=query_embedding,
                top_k=THEME_EXPERT_TOP_K,
                transcript_id=transcript.id,
            )
            for chunk in chunks:
                merged[chunk.chunk_id] = chunk
        return list(merged.values())

    def _tagged_context(self, chunks) -> str:
        """Serialize chunks into a context block tagged with expert identity."""
        return build_citation_context(chunks)

    async def _analyze_topic(self, topic: str) -> ThemeEntry:
        chunks = await self._retrieve_topic_chunks(topic)
        if not chunks:
            return ThemeEntry(topic=topic, themes=[])

        context = self._tagged_context(chunks)
        cache_key = make_cache_key("themes", self._settings.llm_model, topic, context)

        async def _produce() -> dict:
            from src.services.dependencies import get_groq_client

            groq = get_groq_client()
            messages = build_themes_messages(topic=topic, context=context)
            return await groq.parse_json_completion(
                messages, temperature=0.2, max_tokens=4096, task="themes"
            )

        payload = await acached_result(cache_key, _produce)

        available = [chunk_to_dict(chunk) for chunk in chunks]
        themes: list[Theme] = []
        for item in payload.get("themes") or []:
            if not isinstance(item, dict):
                logger.warning("skipping non-dict theme item: %r", item)
                continue
            theme_type = str(item.get("type", "")).strip()
            if theme_type not in {"Consensus", "Disagreement", "Emphasis"}:
                theme_type = "Emphasis"
            citation_items = [
                c for c in (item.get("citations") or []) if isinstance(c, dict)
            ]
            citations, _ = verify_citations(citation_items, available)
            themes.append(
                Theme(
                    type=theme_type,
                    summary=str(item.get("summary", "")).strip(),
                    citations=citations,
                )
            )

        return ThemeEntry(topic=topic, themes=themes)

    async def generate_themes(self):
        """Yield theme data progressively, one topic's themes per event.

        Events: {"type": "meta", "topics": [...]}, then one
        {"type": "topic", "topic": ..., "themes": [...]} per topic, then
        {"type": "done"}.
        """
        guide_path = Path(self._settings.transcript_dir) / "Interview_Guide.txt"
        topics = load_interview_guide(guide_path)

        yield {
            "type": "meta",
            "topics": [{"index": i, "topic": topic} for i, topic in enumerate(topics, start=1)],
        }

        for topic in topics:
            try:
                entry = await self._analyze_topic(topic)
            except Exception as exc:
                logger.exception("theme topic analysis failed for: %s", topic)
                await audit_service.record_error(
                    component="themes",
                    message=f"Theme analysis failed for topic: {topic}",
                    exception_type=type(exc).__name__,
                    endpoint="/api/v1/analysis/themes/stream",
                    method="GET",
                    detail={"topic": topic},
                )
                entry = ThemeEntry(topic=topic, themes=[], error=True)
            yield {
                "type": "topic",
                "topic": topic,
                "themes": [theme.model_dump() for theme in entry.themes],
                "error": entry.error,
            }

        yield {"type": "done"}
