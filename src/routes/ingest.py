from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.database import get_db
from src.repositories.schema.schemas import IngestionResult
from src.services.dependencies import get_embedder_client, get_settings_config
from src.services.ingest_service import IngestService
from src.utils.exceptions.exceptions import IngestionError

router = APIRouter(prefix="/api/v1", tags=["Transcripts"])


@router.post("/transcripts", response_model=IngestionResult)
async def ingest_transcripts(
    session: AsyncSession = Depends(get_db),
    embedder=Depends(get_embedder_client),
    settings=Depends(get_settings_config),
) -> IngestionResult:
    from src.repositories.transcript_repository import TranscriptRepository

    service = IngestService(TranscriptRepository(session), embedder, settings)
    try:
        return await service.ingest_all()
    except IngestionError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc
