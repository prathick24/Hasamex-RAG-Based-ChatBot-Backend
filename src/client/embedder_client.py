from sentence_transformers import SentenceTransformer

from src.settings import Settings
from src.utils.exceptions.exceptions import EmbeddingError
from src.utils.logger import logger


class EmbedderClient:
    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.embedding_model
        self._model: SentenceTransformer | None = None

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            try:
                logger.info("loading_embedding_model", model=self.model_name)
                self._model = SentenceTransformer(self.model_name)
            except Exception as exc:
                raise EmbeddingError(
                    f"Failed to load embedding model '{self.model_name}': {exc}"
                ) from exc
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            model = self._load()
            embeddings = model.encode(
                texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True
            )
            return [embedding.tolist() for embedding in embeddings]
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"Embedding failed: {exc}") from exc

    def embed_one(self, text: str) -> list[float]:
        try:
            return self.embed([text])[0]
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"Embedding failed: {exc}") from exc
