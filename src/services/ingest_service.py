import asyncio
from pathlib import Path

from src.client.embedder_client import EmbedderClient
from src.repositories.schema.schemas import IngestionResult, TranscriptRecord
from src.repositories.transcript_repository import TranscriptRepository
from src.services.cache import purge_by_prefix
from src.settings import Settings
from src.utils.exceptions.exceptions import IngestionError
from src.utils.logger import logger
from src.utils.parser import parse_transcript_file, parse_transcript_text

MAX_CONCURRENT_EMBEDS = 8


def _bundle_expert_answer(content: str, question: str | None) -> str:
    """Make a chunk self-contained by attaching the interviewer's preceding
    question, which carries the timeframe/scope that the answer relies on."""
    if question:
        return f"Q: {question}\nA: {content}"
    return content


class IngestService:
    def __init__(
        self, repository: TranscriptRepository, embedder: EmbedderClient, settings: Settings
    ) -> None:
        self._repository = repository
        self._embedder = embedder
        self._transcript_dir = Path(settings.transcript_dir)

    def _discover_files(self) -> list[Path]:
        if not self._transcript_dir.exists():
            raise IngestionError(f"Transcript directory not found: {self._transcript_dir}")
        files = sorted(
            file
            for file in self._transcript_dir.glob("*.txt")
            if file.name.lower() != "interview_guide.txt"
        )
        if not files:
            raise IngestionError(f"No .txt transcript files found in {self._transcript_dir}")
        return files

    def _build_expert_chunks(
        self, parsed_transcript, include_filename: bool = True
    ) -> list[dict]:
        chunks: list[dict] = []
        pending_question: str | None = None
        for turn in parsed_transcript.turns:
            if turn.speaker == "Interviewer":
                pending_question = turn.content
                continue
            chunk = {
                "speaker": turn.speaker,
                "speaker_index": turn.speaker_index,
                "timestamp": turn.timestamp,
                "content": _bundle_expert_answer(turn.content, pending_question),
            }
            if include_filename:
                chunk["filename"] = parsed_transcript.filename
            chunks.append(chunk)
        return chunks

    async def ingest_all(self) -> IngestionResult:
        try:
            files = self._discover_files()
            parsed = [parse_transcript_file(file) for file in files]

            transcript_records = [
                {
                    "filename": p.filename,
                    "expert_name": p.expert_name,
                    "expert_role": p.expert_role,
                    "market": p.market,
                }
                for p in parsed
            ]

            all_chunks: list[dict] = []
            for parsed_transcript in parsed:
                all_chunks.extend(self._build_expert_chunks(parsed_transcript))

            await self._embed_chunks(all_chunks)

            return await self._repository.ingest(transcript_records, all_chunks)
        except IngestionError:
            raise
        except Exception as exc:
            logger.exception("ingestion_failed")
            raise IngestionError(f"Ingestion failed: {exc}") from exc

    async def _embed_chunks(self, chunks: list[dict]) -> None:
        contents = [chunk["content"] for chunk in chunks]
        for start in range(0, len(contents), MAX_CONCURRENT_EMBEDS):
            batch = contents[start : start + MAX_CONCURRENT_EMBEDS]
            embeddings = await asyncio.to_thread(self._embedder.embed, batch)
            for i, embedding in enumerate(embeddings):
                chunks[start + i]["embedding"] = embedding

    async def ingest_single_file(self, filename: str, content: str) -> dict:
        """Parse and persist one uploaded transcript, replacing any older version
        with the same filename. Returns upload outcome with chunk count."""
        parsed = parse_transcript_text(filename, content)

        transcript_dict = {
            "filename": parsed.filename,
            "expert_name": parsed.expert_name,
            "expert_role": parsed.expert_role,
            "market": parsed.market,
        }
        chunks: list[dict] = self._build_expert_chunks(parsed, include_filename=False)
        await self._embed_chunks(chunks)
        if not chunks:
            raise IngestionError(f"No expert chunks found in {filename}")

        transcript_id, replaced, version = await self._repository.upload_version(
            transcript_dict, chunks
        )
        purged = purge_by_prefix(f"interview_guide_batch::{parsed.filename}::")
        logger.info(
            "transcript_uploaded",
            filename=parsed.filename,
            replaced=replaced,
            version=version,
            chunks=len(chunks),
            cache_purged=purged,
        )
        return {
            "transcript_id": transcript_id,
            "replaced": replaced,
            "version": version,
            "chunk_count": len(chunks),
        }

    async def list_ingested(self) -> list[TranscriptRecord]:
        return await self._repository.list_transcripts()

    async def delete_transcript(self, transcript_id: int) -> bool:
        filename = await self._repository.soft_delete_transcript(transcript_id)
        if filename:
            purge_by_prefix(f"interview_guide_batch::{filename}::")
        return bool(filename)
