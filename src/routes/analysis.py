import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.database import get_db
from src.repositories.schema.schemas import InterviewGuideEntry, ThemeEntry
from src.repositories.transcript_repository import TranscriptRepository
from src.services.dependencies import get_service_deps
from src.services.interview_guide_service import InterviewGuideService
from src.services.theme_service import ThemeService
from src.utils.exceptions.exceptions import LLMError

router = APIRouter(prefix="/api/v1/analysis", tags=["Analysis"])


@router.get("/interview-guide", response_model=list[InterviewGuideEntry])
async def get_interview_guide(
    session: AsyncSession = Depends(get_db),
    dependencies=Depends(get_service_deps),
) -> list[InterviewGuideEntry]:
    service = InterviewGuideService(TranscriptRepository(session), dependencies)
    try:
        return await service.get_interview_guide()
    except LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/interview-guide/stream")
async def stream_interview_guide(
    session: AsyncSession = Depends(get_db),
    dependencies=Depends(get_service_deps),
) -> StreamingResponse:
    service = InterviewGuideService(TranscriptRepository(session), dependencies)

    async def event_stream():
        try:
            async for event in service.generate_interview_guide():
                yield json.dumps(event) + "\n"
        except LLMError as exc:
            yield json.dumps({"type": "error", "detail": exc.message}) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/themes", response_model=list[ThemeEntry])
async def get_themes(
    session: AsyncSession = Depends(get_db),
    dependencies=Depends(get_service_deps),
) -> list[ThemeEntry]:
    service = ThemeService(TranscriptRepository(session), dependencies)
    try:
        return await service.get_themes()
    except LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/themes/stream")
async def stream_themes(
    session: AsyncSession = Depends(get_db),
    dependencies=Depends(get_service_deps),
) -> StreamingResponse:
    service = ThemeService(TranscriptRepository(session), dependencies)

    async def event_stream():
        try:
            async for event in service.generate_themes():
                yield json.dumps(event) + "\n"
        except LLMError as exc:
            yield json.dumps({"type": "error", "detail": exc.message}) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache"},
    )
