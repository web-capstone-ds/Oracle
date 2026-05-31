import os
import psycopg
from psycopg.rows import dict_row

AUTH_DB_HOST = os.getenv("AUTH_DB_HOST", "oracle-db")
AUTH_DB_PORT = os.getenv("AUTH_DB_PORT", "5432")
AUTH_DB_NAME = os.getenv("AUTH_DB_NAME", "oracle")
AUTH_DB_USER = os.getenv("AUTH_DB_USER", "oracle")
AUTH_DB_PASSWORD = os.getenv("AUTH_DB_PASSWORD", "oracle_secret")

async def get_user(operator_id: str) -> dict | None:
    conn_str = f"host={AUTH_DB_HOST} port={AUTH_DB_PORT} dbname={AUTH_DB_NAME} user={AUTH_DB_USER} password={AUTH_DB_PASSWORD}"
    async with await psycopg.AsyncConnection.connect(conn_str, row_factory=dict_row) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT operator_id, password_hash, name, department, phone, role, active "
                "FROM local_user_replica WHERE operator_id = %s",
                (operator_id,)
            )
            return await cur.fetchone()
