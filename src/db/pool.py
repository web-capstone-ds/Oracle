"""DB 커넥션 풀 (Oracle DB + Historian DB).

psycopg 3.x AsyncConnectionPool 사용.
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from config import settings
from utils.logging_config import get_logger

log = get_logger(__name__)

_oracle_pool: AsyncConnectionPool | None = None
_historian_pool: AsyncConnectionPool | None = None


async def open_pools() -> None:
    global _oracle_pool, _historian_pool
    if _oracle_pool is None:
        _oracle_pool = AsyncConnectionPool(
            conninfo=settings.oracle_dsn,
            min_size=settings.oracle_db_pool_min,
            max_size=settings.oracle_db_pool_max,
            open=False,
            name="oracle_pool",
        )
        await _oracle_pool.open()
        await _oracle_pool.wait()
        log.info("oracle_pool_opened", host=settings.oracle_db_host)
    if _historian_pool is None:
        _historian_pool = AsyncConnectionPool(
            conninfo=settings.historian_dsn,
            min_size=settings.historian_db_pool_min,
            max_size=settings.historian_db_pool_max,
            open=False,
            name="historian_pool",
        )
        try:
            await _historian_pool.open()
            await _historian_pool.wait(timeout=5.0)
            log.info("historian_pool_opened", host=settings.historian_db_host)
        except Exception as exc:
            # Historian이 아직 기동 전일 수 있다. 쿼리 시점에 재시도.
            log.warning("historian_pool_open_failed", error=str(exc))


async def close_pools() -> None:
    global _oracle_pool, _historian_pool
    if _oracle_pool is not None:
        await _oracle_pool.close()
        _oracle_pool = None
        log.info("oracle_pool_closed")
    if _historian_pool is not None:
        await _historian_pool.close()
        _historian_pool = None
        log.info("historian_pool_closed")


def oracle_pool() -> AsyncConnectionPool:
    if _oracle_pool is None:
        raise RuntimeError("Oracle pool not opened — call open_pools() first")
    return _oracle_pool


def historian_pool() -> AsyncConnectionPool:
    if _historian_pool is None:
        raise RuntimeError("Historian pool not opened — call open_pools() first")
    return _historian_pool
