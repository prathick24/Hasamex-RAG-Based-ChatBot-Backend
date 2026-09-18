from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from src.client.embedder_client import EmbedderClient
from src.client.groq_client import GroqClient
from src.repositories.transcript_repository import TranscriptRepository
from src.settings import Settings, get_settings
from src.utils.exceptions.exceptions import LLMError


@dataclass
class ServiceDependencies:
    settings: Settings
    embedder: EmbedderClient
    groq: GroqClient | None = None


@lru_cache(maxsize=1)
def get_services() -> ServiceDependencies:
    settings = get_settings()
    embedder = EmbedderClient(settings)
    groq_client = GroqClient(settings=settings) if settings.groq_api_key else None
    return ServiceDependencies(settings=settings, embedder=embedder, groq=groq_client)


def get_service_deps() -> ServiceDependencies:
    return get_services()


def get_embedder_client() -> EmbedderClient:
    return get_services().embedder


def get_groq_client() -> GroqClient:
    services = get_services()
    if services.groq is None:
        raise LLMError("GROQ_API_KEY is not configured")
    return services.groq


def get_transcript_repository(session: AsyncSession) -> TranscriptRepository:
    return TranscriptRepository(session)


def get_settings_config() -> Settings:
    return get_settings()
