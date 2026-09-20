from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "datas"
PROMPT_DIR = PROJECT_ROOT / "src" / "prompt"

DEFAULT_TRANSCRIPT_DIR = str(DATA_DIR)
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIMENSIONS = 384
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_TOP_K = 5
DEFAULT_SIMILARITY_THRESHOLD = 0.5
LLM_RETRY_MAX_ATTEMPTS = 5
LLM_RETRY_WAIT_MIN = 2
LLM_RETRY_WAIT_MAX = 10
GROQ_MIN_REQUEST_INTERVAL = 2.0
GROQ_TOKEN_LIMIT = 8000.0
GROQ_ESTIMATED_TOKENS_PER_REQUEST = 2048.0
LLM_TIMEOUT_SECONDS = 60.0
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "hasamex-transcript-analysis"
    app_version: str = "1.0.0"

    database_url: str = "postgresql+asyncpg://postgres:Admin123@localhost:5432/hasamex"
    groq_api_key: str = ""
    groq_base_url: str = DEFAULT_GROQ_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    top_k: int = DEFAULT_TOP_K
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    transcript_dir: str = DEFAULT_TRANSCRIPT_DIR
    log_level: str = "INFO"
    cache_llm_results: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
