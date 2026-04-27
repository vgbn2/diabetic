"""
diabetic/storage/engine.py

Async SQLAlchemy engine factory for the Bio-Quant Vessel Registry.
Supports SQLite (local dev) and PostgreSQL (Heroku/Cloud Run production).
"""
import os
import logging
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from diabetic.storage.models import Base

logger = logging.getLogger("Bio-Quant.Storage")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_url() -> str:
    """
    Resolve database URL with environment-aware switching.
    Heroku provides postgres:// URLs — SQLAlchemy 2.0+ requires postgresql+asyncpg://.
    """
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        # Heroku postgres:// compatibility fix
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return db_url

    # Local SQLite fallback — stored in the storage directory
    storage_dir = os.path.join(os.path.dirname(__file__))
    db_path = os.path.join(storage_dir, "vessel_registry.db")
    return f"sqlite+aiosqlite:///{db_path}"


def get_engine() -> AsyncEngine:
    """Return the singleton async engine, creating it on first call."""
    global _engine
    if _engine is None:
        url = _build_url()
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        _engine = create_async_engine(
            url,
            connect_args=connect_args,
            echo=False,
            pool_pre_ping=True,
        )
        logger.info("[Storage] Async engine initialized: %s", url.split("@")[-1])  # mask creds
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the reusable async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


async def init_db() -> None:
    """
    Create all tables if they do not exist.
    Called once at application startup (non-blocking, awaitable).
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("[Storage] Vessel Registry schema initialized.")


async def close_db() -> None:
    """Gracefully dispose the engine connection pool on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("[Storage] Engine disposed.")
