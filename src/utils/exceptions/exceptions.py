from src.utils.exceptions.error_codes import (
    ERROR_DB_QUERY_FAILED,
    ERROR_DB_WRITE_FAILED,
    ERROR_EMBEDDING_FAILED,
    ERROR_INGESTION_FAILED,
    ERROR_INVALID_INPUT,
    ERROR_LLM_CALL_FAILED,
    ERROR_LLM_PARSE_FAILED,
    ERROR_TRANSCRIPT_NOT_FOUND,
    ERROR_UNEXPECTED,
    ERROR_VECTOR_SEARCH_FAILED,
)


class ApplicationError(Exception):
    def __init__(
        self, message: str, status_code: int = 500, error_code: str = ERROR_UNEXPECTED
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class ValidationError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=422, error_code=ERROR_INVALID_INPUT)


class TranscriptNotFoundError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404, error_code=ERROR_TRANSCRIPT_NOT_FOUND)


class IngestionError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=500, error_code=ERROR_INGESTION_FAILED)


class RepositoryError(ApplicationError):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message, status_code=status_code, error_code=ERROR_DB_QUERY_FAILED)


class VectorSearchError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=500, error_code=ERROR_VECTOR_SEARCH_FAILED)


class EmbeddingError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=500, error_code=ERROR_EMBEDDING_FAILED)


class LLMError(ApplicationError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message, status_code=status_code, error_code=ERROR_LLM_CALL_FAILED)


class LLMParseError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=502, error_code=ERROR_LLM_PARSE_FAILED)


class LLMRateLimitError(LLMError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=429)


class DatabaseWriteError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=500, error_code=ERROR_DB_WRITE_FAILED)
