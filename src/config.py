"""인증 값은 저장하지 않습니다. 로컬 connections.toml의 연결 이름을 사용합니다."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = os.getenv("AE101_DATABASE", "AE101_SALES")
CONNECTION_NAME = os.getenv("SNOWFLAKE_CONNECTION_NAME", "ae101")

def connect():
    import re
    import snowflake.connector
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", DATABASE):
        raise ValueError("AE101_DATABASE must be a simple unquoted identifier")
    conn = snowflake.connector.connect(connection_name=CONNECTION_NAME)
    conn.autocommit(True)
    try:
        conn.cursor().execute(f"USE DATABASE {DATABASE}")
    except Exception:
        conn.close()
        raise
    return conn
