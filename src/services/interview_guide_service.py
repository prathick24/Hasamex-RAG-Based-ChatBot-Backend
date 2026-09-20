import logging
from pathlib import Path

from src.prompt import build_interview_guide_batch_messages
from src.repositories.schema.schemas import (
    InterviewGuideAnswer,
    InterviewGuideEntry,
)
from src.repositories.transcript_repository import TranscriptRepository
from src.services import audit_service
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

BATCH_SIZE = 3


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

    async def _answer_expert_batch(
        self,
        transcript,
        items: list[tuple[int, str]],
    ) -> list[InterviewGuideAnswer]:
        """Answer several guide questions for one expert in a single LLM call.

        items: list of (question_id, question).
        """
        prepared = [
            {
                "qid": qid,
                "question": question,
                "chunks": await self._retrieve_expert_chunks(transcript.id, question),
            }
            for qid, question in items
        ]
        for item in prepared:
            item["context"] = build_citation_context(item["chunks"]) if item["chunks"] else ""

        results: dict[int, InterviewGuideAnswer] = {}
        for item in prepared:
            if not item["chunks"]:
                results[item["qid"]] = InterviewGuideAnswer(
                    question_id=item["qid"],
                    expert=transcript.expert_name,
                    answer="Not mentioned in this transcript",
                    citations=[],
                )

        groq_items = [item for item in prepared if item["chunks"]]
        if groq_items:
            batch = [(i["qid"], i["question"], i["context"]) for i in groq_items]
            key_hash = make_cache_key(
                "interview_guide_batch",
                self._settings.llm_model,
                transcript.filename,
                transcript.version,
                batch,
            )
            cache_key = f"interview_guide_batch::{transcript.filename}::{key_hash}"

            async def _produce() -> tuple[dict, str]:
                from src.services.dependencies import get_groq_client

                groq = get_groq_client()
                messages = build_interview_guide_batch_messages(
                    transcript.expert_name,
                    batch,
                )
                return (
                    await groq.parse_json_completion(
                        messages,
                        temperature=0.2,
                        task="guide_batch",
                    ),
                    transcript.filename,
                )

            payload, _ = await acached_result(cache_key, _produce)
            by_id: dict[int, dict] = {}
            for a in payload.get("answers") or []:
                if not isinstance(a, dict) or a.get("question_id") is None:
                    continue
                try:
                    qid = int(a["question_id"])
                except (TypeError, ValueError):
                    continue
                by_id[qid] = a

            for item in groq_items:
                item_payload = by_id.get(item["qid"], {})
                available = [chunk_to_dict(chunk) for chunk in item["chunks"]]
                citation_items = [
                    c for c in (item_payload.get("citations") or []) if isinstance(c, dict)
                ]
                citations, _ = verify_citations(citation_items, available)
                answer = str(item_payload.get("answer", "")).strip()
                if not answer:
                    answer = "Not mentioned in this transcript"
                results[item["qid"]] = InterviewGuideAnswer(
                    question_id=item["qid"],
                    expert=transcript.expert_name,
                    answer=answer,
                    citations=citations,
                )

        return [results[item["qid"]] for item in prepared]

    async def generate_interview_guide(self):
        """Yield guide data progressively, one batch of answers per event.

        Events: {"type": "meta", "questions": [...]}, then one
        {"type": "batch", "expert": ..., "answers": [...]} per expert+batch, then
        {"type": "done"}.
        """
        guide_path = Path(self._settings.transcript_dir) / "Interview_Guide.txt"
        questions = load_interview_guide(guide_path)
        transcripts = await self._repository.list_transcripts()

        indexed = list(enumerate(questions, start=1))
        yield {
            "type": "meta",
            "questions": [{"question_id": qid, "question": question} for qid, question in indexed],
        }

        for transcript_record in transcripts:
            transcript = await self._repository.get_transcript(transcript_record.id)
            if transcript is None:
                raise TranscriptNotFoundError(f"Transcript {transcript_record.id} missing")
            for start in range(0, len(indexed), BATCH_SIZE):
                batch = indexed[start : start + BATCH_SIZE]
                try:
                    answers = await self._answer_expert_batch(transcript, batch)
                except Exception as exc:
                    logger.exception(
                        "interview guide batch failed for expert: %s", transcript.expert_name
                    )
                    await audit_service.record_error(
                        component="guide",
                        message=(
                            "Interview guide batch failed for expert: "
                            f"{transcript.expert_name}"
                        ),
                        exception_type=type(exc).__name__,
                        endpoint="/api/v1/analysis/interview-guide/stream",
                        method="GET",
                        detail={"expert": transcript.expert_name},
                    )
                    answers = [
                        InterviewGuideAnswer(
                            question_id=qid,
                            expert=transcript.expert_name,
                            answer=(
                                "Oops - we hit a snag generating this one. "
                                "Please use the Refresh button and we'll try again."
                            ),
                            citations=[],
                        )
                        for qid, _ in batch
                    ]
                yield {
                    "type": "batch",
                    "expert": transcript.expert_name,
                    "answers": [answer.model_dump() for answer in answers],
                }

        yield {"type": "done"}

    async def get_interview_guide(self) -> list[InterviewGuideEntry]:
        guide_path = Path(self._settings.transcript_dir) / "Interview_Guide.txt"
        questions = load_interview_guide(guide_path)
        by_question: dict[int, list[InterviewGuideAnswer]] = {}

        async for event in self.generate_interview_guide():
            if event["type"] != "batch":
                continue
            for answer in event["answers"]:
                by_question.setdefault(answer["question_id"], []).append(
                    InterviewGuideAnswer(**answer)
                )

        return [
            InterviewGuideEntry(
                question_id=qid,
                question=question,
                answers=by_question.get(qid, []),
            )
            for qid, question in enumerate(questions, start=1)
        ]