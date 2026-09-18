from collections.abc import AsyncGenerator

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


db: DatabaseSessionManager = DatabaseSessionManager()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with db.session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
