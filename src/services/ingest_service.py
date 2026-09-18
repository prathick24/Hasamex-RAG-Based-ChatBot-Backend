import asyncio
import logging
from pathlib import Path

from src.client.embedder_client import EmbedderClient
from src.repositories.schema.schemas import IngestionResult
from src.repositories.transcript_repository import TranscriptRepository
from src.settings import Settings
from src.utils.exceptions.exceptions import IngestionError
from src.utils.parser import parse_transcript_file

logger = logging.getLogger("hasamex.ingest")

MAX_CONCURRENT_EMBEDS = 8


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
                for turn in parsed_transcript.turns:
                    if turn.speaker == "Interviewer":
                        continue
                    all_chunks.append(
                        {
                            "filename": parsed_transcript.filename,
                            "speaker": turn.speaker,
                            "speaker_index": turn.speaker_index,
                            "timestamp": turn.timestamp,
                            "content": turn.content,
                        }
                    )

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
