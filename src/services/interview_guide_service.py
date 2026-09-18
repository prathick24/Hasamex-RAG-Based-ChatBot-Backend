import logging
from pathlib import Path

from src.prompt import build_interview_guide_messages
from src.repositories.schema.schemas import (
    InterviewGuideAnswer,
    InterviewGuideEntry,
)
from src.repositories.transcript_repository import TranscriptRepository
from src.services.cache import acached_result, make_cache_key
from src.services.citation_utils import (
    build_citation_context,
    chunk_to_dict,
    verify_citations,
)
from src.settings import Settings
from src.utils.exceptions.exceptions import TranscriptNotFoundError
from src.utils.parser import load_interview_guide

logger = logging.getLogger("hasamex.interview_guide")


class InterviewGuideService:
    def __init__(self, repository: TranscriptRepository, dependencies) -> None:
        self._repository = repository
        self._deps = dependencies
        self._settings: Settings = dependencies.settings

    async def _retrieve_expert_chunks(self, transcript_id: int, question: str, top_k: int = 3):
        query_embedding = self._deps.embedder.embed_one(question)
        return await self._repository.similarity_search(
            query_embedding=query_embedding,
            top_k=top_k,
            transcript_id=transcript_id,
            min_cosine_distance=self._settings.similarity_threshold,
        )

    async def _answer_for_expert(
        self,
        transcript,
        question_id: int,
        question: str,
    ) -> InterviewGuideAnswer:
        chunks = await self._retrieve_expert_chunks(transcript.id, question)
        if not chunks:
            return InterviewGuideAnswer(
                question_id=question_id,
                expert=transcript.expert_name,
                answer="Not mentioned in this transcript",
                citations=[],
            )

        context = build_citation_context(chunks)
        cache_key = make_cache_key(
            "interview_guide",
            self._settings.llm_model,
            transcript.filename,
            question_id,
            context,
        )

        async def _produce() -> tuple[dict, str]:
            from src.services.dependencies import get_groq_client

            groq = get_groq_client()
            messages = build_interview_guide_messages(
                question_id=question_id,
                question=question,
                expert_name=transcript.expert_name,
                context=context,
            )
            return await groq.parse_json_completion(messages, temperature=0.2), context

        payload, _ = await acached_result(cache_key, _produce)

        available = [chunk_to_dict(chunk) for chunk in chunks]
        citations, _ = verify_citations(payload.get("citations", []), available)

        answer = str(payload.get("answer", "")).strip()
        if not answer:
            answer = "Not mentioned in this transcript"

        return InterviewGuideAnswer(
            question_id=question_id,
            expert=transcript.expert_name,
            answer=answer,
            citations=citations,
        )

    async def get_interview_guide(self) -> list[InterviewGuideEntry]:
        guide_path = Path(self._settings.transcript_dir) / "Interview_Guide.txt"
        questions = load_interview_guide(guide_path)
        transcripts = await self._repository.list_transcripts()

        entries: list[InterviewGuideEntry] = []
        for question_id, question in enumerate(questions, start=1):
            answers = []
            for transcript_record in transcripts:
                transcript = await self._repository.get_transcript(transcript_record.id)
                if transcript is None:
                    raise TranscriptNotFoundError(f"Transcript {transcript_record.id} missing")
                answers.append(await self._answer_for_expert(transcript, question_id, question))
            entries.append(
                InterviewGuideEntry(question_id=question_id, question=question, answers=answers)
            )

        return entries
