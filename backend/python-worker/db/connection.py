"""
db.connection — asyncpg Connection Pool Management for Neon PostgreSQL

Provides async connection pooling, JSON/JSONB codec registration,
context managers, and health check utilities for SentriAI Python Worker.
"""
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import asyncpg
import dotenv

logger = logging.getLogger("sentriai.db")

# Global pool reference
_pool: Optional[asyncpg.Pool] = None


def get_database_url() -> str:
    """
    Retrieve database URL from environment or .env files.
    Searches backend/.env, .env in parent directories, or system env.
    """
    # Try current directory and typical parent paths
    possible_env_paths = [
        "backend/.env",
        ".env",
        "../.env",
        "../../backend/.env",
    ]
    for env_path in possible_env_paths:
        if os.path.exists(env_path):
            dotenv.load_dotenv(env_path)
            break
    else:
        # Fallback to standard dotenv loading
        dotenv.load_dotenv()

    url = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise ValueError(
            "Database URL not found. Please set NEON_DATABASE_URL in backend/.env"
        )
    return url


async def _init_connection(conn: asyncpg.Connection) -> None:
    """
    Configure connection codecs for seamless JSONB handling.
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_db_pool(
    dsn: Optional[str] = None,
    min_size: int = 1,
    max_size: int = 10,
    timeout: float = 30.0,
) -> asyncpg.Pool:
    """
    Initialize global asyncpg connection pool.
    """
    global _pool
    if _pool is not None:
        logger.warning("Database pool already initialized. Returning existing pool.")
        return _pool

    database_url = dsn or get_database_url()
    logger.info("Initializing database pool (min_size=%d, max_size=%d)...", min_size, max_size)

    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=min_size,
        max_size=max_size,
        timeout=timeout,
        init=_init_connection,
    )
    logger.info("Database pool successfully initialized.")
    return _pool


def get_db_pool() -> asyncpg.Pool:
    """
    Get active database pool. Raises RuntimeError if pool is not initialized.
    """
    if _pool is None:
        raise RuntimeError(
            "Database pool is not initialized. Call 'await init_db_pool()' first."
        )
    return _pool


async def close_db_pool() -> None:
    """
    Gracefully close global database pool.
    """
    global _pool
    if _pool is not None:
        logger.info("Closing database pool...")
        await _pool.close()
        _pool = None
        logger.info("Database pool closed.")


@asynccontextmanager
async def get_db_connection() -> AsyncIterator[asyncpg.Connection]:
    """
    Async context manager to acquire a connection from the pool.
    Usage:
        async with get_db_connection() as conn:
            val = await conn.fetchval('SELECT 1')
    """
    pool = get_db_pool()
    async with pool.acquire() as conn:
        yield conn


async def check_db_health() -> bool:
    """
    Test database connectivity with a simple SELECT 1.
    """
    try:
        pool = get_db_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT 1")
            return val == 1
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return False
