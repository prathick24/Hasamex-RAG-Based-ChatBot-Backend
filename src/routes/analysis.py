from fastapi import APIRouter, Depends, HTTPException
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
