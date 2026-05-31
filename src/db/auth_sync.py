"""Web-Backend → Oracle local_user_replica 단방향 증분 동기화.

동작 방식:
  1. oracle DB에서 현재 max(synced_version)을 조회한다.
  2. Web-Backend GET /api/auth/snapshot?since=<version> 을 호출한다.
  3. 응답의 users[]를 UPSERT (INSERT … ON CONFLICT DO UPDATE) 한다.
  4. 변경된 버전을 synced_version에 기록한다.

네트워크 단절이나 Web-Backend 비기동 시에는 로그만 남기고 다음 주기에 재시도.
"""

from __future__ import annotations

import asyncio

import httpx
from psycopg.rows import dict_row

from config import settings
from db.pool import oracle_pool
from utils.logging_config import get_logger

log = get_logger(__name__)

_UPSERT_SQL = """
INSERT INTO local_user_replica
    (operator_id, password_hash, name, department, phone, role, active, updated_at, synced_at)
VALUES
    (%(operator_id)s, %(password_hash)s, %(name)s, %(department)s, %(phone)s,
     %(role)s, %(active)s, %(updated_at)s, NOW())
ON CONFLICT (operator_id) DO UPDATE SET
    password_hash = EXCLUDED.password_hash,
    name          = EXCLUDED.name,
    department    = EXCLUDED.department,
    phone         = EXCLUDED.phone,
    role          = EXCLUDED.role,
    active        = EXCLUDED.active,
    updated_at    = EXCLUDED.updated_at,
    synced_at     = NOW()
"""

_GET_SYNCED_VERSION_SQL = """
SELECT COALESCE(MAX(EXTRACT(EPOCH FROM updated_at)), 0)::BIGINT AS max_version
FROM local_user_replica
"""

# oracle_judgments의 version 컬럼 방식과 맞추기 위해 별도 메타 테이블 없이
# Web-Backend 응답의 version(숫자 단조증가)을 oracle DB에 보관한다.
_GET_VERSION_SQL = "SELECT COALESCE(MAX(synced_version), 0) FROM local_user_meta"
_UPSERT_VERSION_SQL = """
INSERT INTO local_user_meta (id, synced_version)
VALUES (1, %(version)s)
ON CONFLICT (id) DO UPDATE SET synced_version = EXCLUDED.synced_version
"""


async def _ensure_meta_table() -> None:
    """local_user_meta 테이블이 없으면 생성 (마이그레이션 실행 전 대비)."""
    async with oracle_pool().connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS local_user_meta (
                id              INT PRIMARY KEY DEFAULT 1,
                synced_version  BIGINT NOT NULL DEFAULT 0,
                CHECK (id = 1)
            )
        """)
        await conn.execute("""
            INSERT INTO local_user_meta (id, synced_version) VALUES (1, 0)
            ON CONFLICT (id) DO NOTHING
        """)


async def _fetch_snapshot(since: int) -> dict | None:
    url = f"{settings.web_backend_url}/api/auth/snapshot"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params={"since": since})
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        log.warning("auth_snapshot_http_error", status=exc.response.status_code, url=url)
    except Exception as exc:
        log.warning("auth_snapshot_fetch_failed", error=str(exc), url=url)
    return None


async def sync_once() -> int:
    """증분 동기화 1회. 반환값: UPSERT된 행 수."""
    await _ensure_meta_table()

    # 현재 동기화된 version 조회
    async with oracle_pool().connection(row_factory=dict_row) as conn:
        row = await (await conn.execute(_GET_VERSION_SQL)).fetchone()
    since = row[0] if row else 0

    data = await _fetch_snapshot(since)
    if data is None:
        return 0

    users = data.get("users", [])
    new_version = data.get("version", since)

    if not users:
        # 변경 없음 — version만 갱신
        if new_version > since:
            async with oracle_pool().connection() as conn:
                await conn.execute(_UPSERT_VERSION_SQL, {"version": new_version})
        return 0

    async with oracle_pool().connection() as conn:
        for u in users:
            await conn.execute(_UPSERT_SQL, {
                "operator_id":  u["operatorId"],
                "password_hash": u["passwordHash"],
                "name":         u.get("name"),
                "department":   u.get("department"),
                "phone":        u.get("phone"),
                "role":         u["role"],
                "active":       u["active"],
                "updated_at":   u["updatedAt"],
            })
        await conn.execute(_UPSERT_VERSION_SQL, {"version": new_version})

    log.info("auth_snapshot_synced", upserted=len(users), version=new_version)
    return len(users)


async def run_sync_loop(stop_event: asyncio.Event) -> None:
    """앱 수명 동안 주기적으로 sync_once()를 호출한다."""
    # 시작 직후 1회 즉시 동기화
    try:
        await sync_once()
    except Exception as exc:
        log.error("auth_sync_initial_failed", error=str(exc))

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.auth_snapshot_interval_sec,
            )
        except asyncio.TimeoutError:
            pass  # 정상 주기 도래

        if stop_event.is_set():
            break

        try:
            await sync_once()
        except Exception as exc:
            log.error("auth_sync_periodic_failed", error=str(exc))
