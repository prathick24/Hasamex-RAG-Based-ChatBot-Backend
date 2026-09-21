import logging

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.database import get_db
from src.repositories.schema.schemas import (
    TranscriptListResult,
    UploadBatchResult,
    UploadFileResult,
)
from src.services.dependencies import get_embedder_client, get_settings_config
from src.services.ingest_service import IngestService
from src.utils.exceptions.exceptions import ValidationError

logger = logging.getLogger("hasamex.ingest")

router = APIRouter(prefix="/api/v1", tags=["Transcripts"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@router.post("/transcripts/upload", response_model=UploadBatchResult)
async def upload_transcripts(
    files: list[UploadFile] = File(default_factory=list),
    session: AsyncSession = Depends(get_db),
    embedder=Depends(get_embedder_client),
    settings=Depends(get_settings_config),
) -> UploadBatchResult:
    from src.repositories.transcript_repository import TranscriptRepository

    service = IngestService(TranscriptRepository(session), embedder, settings)
    batch = UploadBatchResult()
    for file in files:
        filename = file.filename or ""
        if not filename.lower().endswith(".txt"):
            batch.results.append(
                UploadFileResult(
                    filename=filename, status="error", reason="Only .txt files are accepted"
                )
            )
            continue
        try:
            raw = await file.read()
            if not raw:
                batch.results.append(
                    UploadFileResult(filename=filename, status="error", reason="File is empty")
                )
                continue
            if len(raw) > MAX_UPLOAD_BYTES:
                batch.results.append(
                    UploadFileResult(
                        filename=filename, status="error", reason="File exceeds 5 MB limit"
                    )
                )
                continue
            outcome = await service.ingest_single_file(filename, raw.decode("utf-8"))
            batch.results.append(
                UploadFileResult(
                    filename=filename,
                    status="replaced" if outcome["replaced"] else "uploaded",
                    transcript_id=outcome["transcript_id"],
                    version=outcome["version"],
                    chunk_count=outcome["chunk_count"],
                )
            )
            batch.succeeded += 1
        except ValidationError as exc:
            batch.results.append(
                UploadFileResult(filename=filename, status="error", reason=str(exc))
            )
        except Exception:
            logger.exception("upload_failed filename=%s", filename)
            batch.results.append(
                UploadFileResult(filename=filename, status="error", reason="Failed to process file")
            )
    batch.processed = len(files)
    return batch


@router.get("/transcripts", response_model=TranscriptListResult)
async def list_transcripts(
    session: AsyncSession = Depends(get_db),
    embedder=Depends(get_embedder_client),
    settings=Depends(get_settings_config),
) -> TranscriptListResult:
    from src.repositories.transcript_repository import TranscriptRepository

    service = IngestService(TranscriptRepository(session), embedder, settings)
    return TranscriptListResult(transcripts=await service.list_ingested())