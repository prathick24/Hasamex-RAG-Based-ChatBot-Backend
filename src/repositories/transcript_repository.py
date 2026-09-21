from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Chunk, Transcript
from src.repositories.schema.schemas import (
    ChunkWithTranscript,
    IngestionResult,
    TranscriptRecord,
)
from src.utils.exceptions.exceptions import (
    DatabaseWriteError,
    RepositoryError,
    TranscriptNotFoundError,
)


class TranscriptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_transcripts(self, records: list[dict]) -> list[int]:
        try:
            models = [Transcript(**record) for record in records]
            self._session.add_all(models)
            await self._session.flush()
            return [model.id for model in models]
        except Exception as exc:
            await self._session.rollback()
            raise DatabaseWriteError(f"Failed to write transcripts: {exc}") from exc

    async def get_active_transcript_by_filename(self, filename: str) -> Transcript | None:
        try:
            stmt = select(Transcript).where(
                Transcript.filename == filename,
                Transcript.is_active.is_(True),
            )
            result = await self._session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryError(f"Failed to query transcript {filename}") from exc

    async def get_transcript(self, transcript_id: int) -> Transcript:
        try:
            stmt = select(Transcript).where(Transcript.id == transcript_id)
            result = await self._session.execute(stmt)
            transcript = result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryError(f"Failed to query transcript {transcript_id}") from exc
        if transcript is None:
            raise TranscriptNotFoundError(f"Transcript {transcript_id} not found")
        return transcript

    async def list_transcripts(self) -> list[TranscriptRecord]:
        try:
            stmt = select(Transcript).where(Transcript.is_active.is_(True)).order_by(Transcript.id)
            result = await self._session.execute(stmt)
            return [TranscriptRecord.model_validate(t) for t in result.scalars()]
        except Exception as exc:
            raise RepositoryError("Failed to list transcripts") from exc

    async def get_next_version(self, filename: str) -> int:
        """Next version for a filename = max existing version + 1 (0 -> 1)."""
        try:
            stmt = select(func.max(Transcript.version)).where(Transcript.filename == filename)
            max_version = (await self._session.execute(stmt)).scalar_one_or_none()
            return (int(max_version) if max_version is not None else 0) + 1
        except Exception as exc:
            raise RepositoryError(f"Failed to query version for transcript {filename}") from exc

    async def _ensure_transcripts(self, records: list[dict]) -> tuple[dict[str, int], int]:
        """Insert transcripts; return ({filename: id}, created_count) for all (existing or new)."""
        try:
            existing_stmt = select(Transcript.filename, Transcript.id).where(
                Transcript.is_active.is_(True)
            )
            existing = dict((await self._session.execute(existing_stmt)).all())

            new_records = [r for r in records if r["filename"] not in existing]
            for record in new_records:
                record["version"] = await self.get_next_version(record["filename"])
            if new_records:
                await self.add_transcripts(new_records)

            updated = dict((await self._session.execute(existing_stmt)).all())
            return updated, len(new_records)
        except DatabaseWriteError:
            raise
        except Exception as exc:
            raise RepositoryError("Failed to ensure transcripts") from exc

    async def add_chunks(self, chunks: list[dict]) -> int:
        """Insert chunks with ON CONFLICT DO NOTHING semantics via NOT EXISTS guard."""
        try:
            inserted = 0
            for chunk in chunks:
                exists_stmt = select(Chunk.id).where(
                    Chunk.transcript_id == chunk["transcript_id"],
                    Chunk.speaker_index == chunk["speaker_index"],
                )
                exists = (await self._session.execute(exists_stmt)).scalar_one_or_none()
                if exists is None:
                    self._session.add(Chunk(**chunk))
                    inserted += 1
            await self._session.flush()
            return inserted
        except Exception as exc:
            await self._session.rollback()
            raise DatabaseWriteError(f"Failed to write chunks: {exc}") from exc

    async def _update_chunk_counts(self) -> None:
        """Refresh chunk_count on every active transcript from actual chunk rows."""
        try:
            counts_stmt = (
                select(Chunk.transcript_id, func.count())
                .join(Transcript, Chunk.transcript_id == Transcript.id)
                .where(Transcript.is_active.is_(True))
                .group_by(Chunk.transcript_id)
            )
            counts = (await self._session.execute(counts_stmt)).all()
            for transcript_id, count in counts:
                await self._session.execute(
                    update(Transcript)
                    .where(Transcript.id == transcript_id)
                    .values(chunk_count=count)
                )
        except Exception as exc:
            await self._session.rollback()
            raise RepositoryError(f"Failed to refresh chunk counts: {exc}") from exc

    async def count_transcripts(self) -> int:
        try:
            stmt = (
                select(func.count()).select_from(Transcript).where(Transcript.is_active.is_(True))
            )
            return int((await self._session.execute(stmt)).scalar_one())
        except Exception as exc:
            raise RepositoryError("Failed to count transcripts") from exc

    async def count_chunks(self) -> int:
        try:
            stmt = (
                select(func.count())
                .select_from(Chunk)
                .join(Transcript, Chunk.transcript_id == Transcript.id)
                .where(Transcript.is_active.is_(True))
            )
            return int((await self._session.execute(stmt)).scalar_one())
        except Exception as exc:
            raise RepositoryError("Failed to count chunks") from exc

    async def ingest(
        self, transcript_records: list[dict], all_chunks: list[dict]
    ) -> IngestionResult:
        """Idempotent ingestion of transcripts + chunks. Returns final + created counts."""
        filename_map, created_transcripts = await self._ensure_transcripts(transcript_records)
        final_transcripts = len(filename_map)

        for chunk in all_chunks:
            filename = chunk.pop("filename", None)
            chunk["transcript_id"] = filename_map.get(filename, -1)

        inserted_chunks = await self.add_chunks(all_chunks)
        await self._update_chunk_counts()
        await self._session.commit()
        final_chunks = await self.count_chunks()

        return IngestionResult(
            transcripts_count=final_transcripts,
            chunks_count=final_chunks,
            loaded=True,
            created_transcripts=created_transcripts,
            created_chunks=inserted_chunks,
        )

    async def upload_version(self, record: dict, chunks: list[dict]) -> tuple[int, bool, int]:
        """Insert a new transcript version under one filename.

        Deactivates any currently active transcript with the same filename, so
        only one active version exists at a time. Returns
        (new transcript_id, replaced, version).
        """
        try:
            filename = record["filename"]
            existing = await self.get_active_transcript_by_filename(filename)
            replaced = existing is not None
            version = await self.get_next_version(filename)
            if existing is not None:
                existing.is_active = False

            transcript = Transcript(
                **record, version=version, is_active=True, chunk_count=len(chunks)
            )
            self._session.add(transcript)
            await self._session.flush()
            for chunk in chunks:
                self._session.add(Chunk(**chunk, transcript_id=transcript.id))
            await self._session.commit()
            return transcript.id, replaced, version
        except Exception as exc:
            await self._session.rollback()
            raise DatabaseWriteError(
                f"Failed to write transcript {record.get('filename')}: {exc}"
            ) from exc

    async def similarity_search(
        self,
        query_embedding: list[float],
        top_k: int,
        transcript_id: int | None = None,
        min_cosine_distance: float | None = None,
    ) -> list[ChunkWithTranscript]:
        try:
            order_expr = Chunk.embedding.cosine_distance(query_embedding)
            stmt = (
                select(
                    Chunk,
                    Transcript.filename,
                    Transcript.expert_name,
                    Transcript.market,
                    order_expr.label("distance"),
                )
                .join(Transcript, Chunk.transcript_id == Transcript.id)
                .where(Transcript.is_active.is_(True))
                .order_by(order_expr.asc())
                .limit(top_k)
            )

            if transcript_id is not None:
                stmt = stmt.where(Chunk.transcript_id == transcript_id)

            result = await self._session.execute(stmt)
            rows = result.all()

            items = [
                ChunkWithTranscript(
                    chunk_id=row.Chunk.id,
                    transcript_file=row.filename,
                    expert_name=row.expert_name,
                    market=row.market,
                    timestamp=row.Chunk.timestamp,
                    content=row.Chunk.content,
                    distance=float(row.distance) if row.distance is not None else None,
                )
                for row in rows
            ]
            if min_cosine_distance is not None:
                items = [
                    item
                    for item in items
                    if item.distance is not None and item.distance <= min_cosine_distance
                ]
            return items
        except Exception as exc:
            raise RepositoryError(f"Vector search failed: {exc}") from exc

    async def question_search(
        self,
        query_embedding: list[float],
        top_k: int,
        transcript_id: int | None = None,
        min_cosine_distance: float | None = None,
    ) -> list[ChunkWithTranscript]:
        """Search chunks by similarity of the interviewer question only.

        Guide questions are fixed and closely match the interviewer questions,
        so matching on the question embedding (instead of the whole Q+A blob)
        ranks the right chunk much higher. Returns the full Q+A bundles of the
        best-matching questions.
        """
        try:
            order_expr = Chunk.question_embedding.cosine_distance(query_embedding)
            stmt = (
                select(
                    Chunk,
                    Transcript.filename,
                    Transcript.expert_name,
                    Transcript.market,
                    order_expr.label("distance"),
                )
                .join(Transcript, Chunk.transcript_id == Transcript.id)
                .where(Transcript.is_active.is_(True))
                .where(Chunk.question_embedding.is_not(None))
                .order_by(order_expr.asc())
                .limit(top_k)
            )

            if transcript_id is not None:
                stmt = stmt.where(Chunk.transcript_id == transcript_id)

            result = await self._session.execute(stmt)
            rows = result.all()

            items = [
                ChunkWithTranscript(
                    chunk_id=row.Chunk.id,
                    transcript_file=row.filename,
                    expert_name=row.expert_name,
                    market=row.market,
                    timestamp=row.Chunk.timestamp,
                    content=row.Chunk.content,
                    distance=float(row.distance) if row.distance is not None else None,
                )
                for row in rows
            ]
            if min_cosine_distance is not None:
                items = [
                    item
                    for item in items
                    if item.distance is not None and item.distance <= min_cosine_distance
                ]
            return items
        except Exception as exc:
            raise RepositoryError(f"Question vector search failed: {exc}") from exc

    async def keyword_search(
        self,
        query: str,
        top_k: int,
        transcript_id: int | None = None,
    ) -> list[ChunkWithTranscript]:
        try:
            terms = [term for term in query.split() if len(term) > 2]
            stmt = (
                select(Chunk, Transcript.filename, Transcript.expert_name, Transcript.market)
                .join(Transcript, Chunk.transcript_id == Transcript.id)
                .where(Transcript.is_active.is_(True))
            )
            for term in terms:
                stmt = stmt.where(Chunk.content.ilike(f"%{term}%"))
            if transcript_id is not None:
                stmt = stmt.where(Chunk.transcript_id == transcript_id)
            stmt = stmt.limit(top_k)

            result = await self._session.execute(stmt)
            return [
                ChunkWithTranscript(
                    chunk_id=row.Chunk.id,
                    transcript_file=row.filename,
                    expert_name=row.expert_name,
                    market=row.market,
                    timestamp=row.Chunk.timestamp,
                    content=row.Chunk.content,
                    distance=None,
                )
                for row in result.all()
            ]
        except Exception as exc:
            raise RepositoryError(f"Keyword search failed: {exc}") from exc

    async def pgvector_available(self) -> bool:
        try:
            stmt = text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            result = await self._session.execute(stmt)
            return result.scalar_one_or_none() is not None
        except Exception:
            return False

    async def tables_available(self) -> bool:
        try:
            for table_name in ("transcripts", "chunks"):
                stmt = text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = :name"
                )
                result = await self._session.execute(stmt, {"name": table_name})
                if result.scalar_one_or_none() is None:
                    return False
            return True
        except Exception:
            return False

    async def delete_all_transcripts(self) -> None:
        try:
            await self._session.execute(delete(Chunk))
            await self._session.execute(delete(Transcript))
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise DatabaseWriteError(f"Failed to clear transcripts: {exc}") from exc
