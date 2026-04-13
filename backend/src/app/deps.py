"""Dependency injection for FastAPI endpoints."""

from collections.abc import AsyncGenerator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# --- Database ---
_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)

# --- Redis ---
_redis: aioredis.Redis | None = None

# --- API Key Auth ---
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def init_db() -> None:
    """Initialize database — create tables if needed (dev only, use Alembic in prod)."""
    from app.models import Base

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose database engine on shutdown."""
    await _engine.dispose()


async def init_redis() -> None:
    """Initialize Redis connection."""
    global _redis
    _redis = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=20,
    )
    # Test connection
    await _redis.ping()


async def close_redis() -> None:
    """Close Redis connection on shutdown."""
    if _redis:
        await _redis.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_redis() -> aioredis.Redis:
    """Return the Redis client."""
    if _redis is None:
        raise RuntimeError("Redis not initialized")
    return _redis


async def verify_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """Verify the API key from the X-API-Key header."""
    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    if api_key != settings.API_KEY.get_secret_value():
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key


# Type aliases for dependency injection
DB = Annotated[AsyncSession, Depends(get_db)]
Redis = Annotated[aioredis.Redis, Depends(get_redis)]
Auth = Annotated[str, Depends(verify_api_key)]
