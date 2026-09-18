import logging
from pathlib import Path

from src.prompt import build_themes_messages
from src.repositories.schema.schemas import Theme, ThemeEntry
from src.repositories.transcript_repository import TranscriptRepository
from src.services.cache import acached_result, make_cache_key
from src.services.citation_utils import (
    build_citation_context,
    chunk_to_dict,
    verify_citations,
)
from src.settings import Settings
from src.utils.parser import load_interview_guide

logger = logging.getLogger("hasamex.themes")


class ThemeService:
    def __init__(self, repository: TranscriptRepository, dependencies) -> None:
        self._repository = repository
        self._deps = dependencies
        self._settings: Settings = dependencies.settings

    async def _retrieve_topic_chunks(self, topic: str, top_k: int = 3, per_expert: bool = True):
        query_embedding = self._deps.embedder.embed_one(topic)
        chunks = await self._repository.similarity_search(
            query_embedding=query_embedding,
            top_k=top_k,
            min_cosine_distance=self._settings.similarity_threshold,
        )
        return chunks

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
            return await groq.parse_json_completion(messages, temperature=0.2)

        payload = await acached_result(cache_key, _produce)

        available = [chunk_to_dict(chunk) for chunk in chunks]
        themes: list[Theme] = []
        for item in payload.get("themes", []):
            theme_type = str(item.get("type", "")).strip()
            if theme_type not in {"Consensus", "Disagreement", "Emphasis"}:
                theme_type = "Emphasis"
            citations, _ = verify_citations(item.get("citations", []), available)
            themes.append(
                Theme(
                    type=theme_type,
                    summary=str(item.get("summary", "")).strip(),
                    citations=citations,
                )
            )

        return ThemeEntry(topic=topic, themes=themes)

    async def get_themes(self) -> list[ThemeEntry]:
        guide_path = Path(self._settings.transcript_dir) / "Interview_Guide.txt"
        topics = load_interview_guide(guide_path)

        entries = []
        for topic in topics:
            entries.append(await self._analyze_topic(topic))
        return entries
