"""auth_sync.py 단위 테스트.

DB와 HTTP 모두 mock — 네트워크/DB 없이 실행된다.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def snapshot_payload():
    return {
        "version": 5,
        "users": [
            {
                "operatorId": "EMP001",
                "passwordHash": "$2b$12$xxx",
                "name": "유민호",
                "department": "A동",
                "phone": "010-1789-6815",
                "role": "ADMIN",
                "active": True,
                "updatedAt": "2026-05-31T00:00:00+00:00",
            },
            {
                "operatorId": "EMP004",
                "passwordHash": "$2b$12$yyy",
                "name": "이재혁",
                "department": "품질관리팀",
                "phone": "010-3113-6985",
                "role": "INSPECTOR",
                "active": True,
                "updatedAt": "2026-05-31T00:00:00+00:00",
            },
        ],
        "checksum": "abc123",
    }


@pytest.mark.asyncio
async def test_sync_once_upserts_all_users(snapshot_payload):
    """정상 응답 시 모든 users를 UPSERT하고 version을 저장한다."""
    from db.auth_sync import sync_once

    # oracle_pool 및 HTTP 클라이언트 mock
    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.execute = AsyncMock(return_value=AsyncMock(fetchone=AsyncMock(return_value=(0,))))

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=snapshot_payload)

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(return_value=mock_resp)

    with (
        patch("db.auth_sync.oracle_pool", return_value=mock_pool),
        patch("db.auth_sync._ensure_meta_table", new_callable=AsyncMock),
        patch("httpx.AsyncClient", return_value=mock_http),
    ):
        upserted = await sync_once()

    assert upserted == 2


@pytest.mark.asyncio
async def test_sync_once_returns_zero_on_http_error():
    """Web-Backend 연결 실패 시 0을 반환하고 예외를 전파하지 않는다."""
    import httpx

    from db.auth_sync import sync_once

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.execute = AsyncMock(return_value=AsyncMock(fetchone=AsyncMock(return_value=(0,))))

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

    with (
        patch("db.auth_sync.oracle_pool", return_value=mock_pool),
        patch("db.auth_sync._ensure_meta_table", new_callable=AsyncMock),
        patch("httpx.AsyncClient", return_value=mock_http),
    ):
        upserted = await sync_once()

    assert upserted == 0


@pytest.mark.asyncio
async def test_sync_once_empty_users_updates_version():
    """변경 없음(users=[])이어도 version은 갱신한다."""
    from db.auth_sync import sync_once

    empty_payload = {"version": 10, "users": [], "checksum": "abc"}

    execute_calls: list[str] = []

    async def fake_execute(sql, params=None):
        execute_calls.append(sql.strip().split()[0])
        return AsyncMock(fetchone=AsyncMock(return_value=(0,)))

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.execute = fake_execute

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn)

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=empty_payload)

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(return_value=mock_resp)

    with (
        patch("db.auth_sync.oracle_pool", return_value=mock_pool),
        patch("db.auth_sync._ensure_meta_table", new_callable=AsyncMock),
        patch("httpx.AsyncClient", return_value=mock_http),
    ):
        upserted = await sync_once()

    assert upserted == 0
    # version 갱신 INSERT가 실행됐는지 확인
    assert "INSERT" in execute_calls
