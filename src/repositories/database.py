from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class DatabaseSessionManager:
    _engine: AsyncEngine | None = None
    _sessionmaker: async_sessionmaker[AsyncSession] | None = None

    def init(self, database_url: str) -> None:
        self._engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)

    async def close(self) -> None:
        if self._engine is None:
            return
        await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None

    def session(self) -> AsyncSession:
        if self._sessionmaker is None:
            raise RuntimeError("DatabaseSessionManager is not initialized")
        return self._sessionmaker()

    async def create_tables(self) -> None:
        if self._engine is None:
            raise RuntimeError("DatabaseSessionManager is not initialized")
        from src.models import Base

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        if self._engine.dialect.name == "postgresql":
            await self._run_startup_migrations()

    async def _run_startup_migrations(self) -> None:
        """Bring pre-versioning tables up to date (no alembic in this project).

        create_all only creates missing tables, so existing databases need the
        new columns and the username-uniqueness replaced by a partial unique
        index that only applies to active transcripts.
        """
        statements = (
            "ALTER TABLE transcripts "
            "ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE transcripts "
            "ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE transcripts DROP CONSTRAINT IF EXISTS transcripts_filename_key",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_transcripts_active_filename "
            "ON transcripts (filename) WHERE is_active",
            "UPDATE transcripts t "
            "SET chunk_count = sub.c "
            "FROM (SELECT transcript_id, COUNT(*) AS c FROM chunks GROUP BY transcript_id) sub "
            "WHERE t.id = sub.transcript_id",
        )
        async with self._engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))


db: DatabaseSessionManager = DatabaseSessionManager()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with db.session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
