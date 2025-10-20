import json
import sqlite3
from pathlib import Path

from draft_analyst.config import CACHE_DB


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or CACHE_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT PRIMARY KEY,
            region TEXT NOT NULL,
            patch TEXT,
            is_pro INTEGER DEFAULT 0,
            data JSON NOT NULL,
            fetched_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS champion_data (
            patch TEXT NOT NULL,
            data JSON NOT NULL,
            fetched_at INTEGER NOT NULL,
            PRIMARY KEY (patch)
        );

        CREATE TABLE IF NOT EXISTS api_cache (
            url TEXT PRIMARY KEY,
            response JSON NOT NULL,
            fetched_at INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_matches_region ON matches(region);
        CREATE INDEX IF NOT EXISTS idx_matches_patch ON matches(patch);
        CREATE INDEX IF NOT EXISTS idx_matches_pro ON matches(is_pro);
    """)
    conn.commit()


def cache_get(conn: sqlite3.Connection, url: str) -> dict | None:
    row = conn.execute(
        "SELECT response FROM api_cache WHERE url = ?", (url,)
    ).fetchone()
    if row:
        return json.loads(row["response"])
    return None


def cache_set(conn: sqlite3.Connection, url: str, data: dict):
    import time
    conn.execute(
        "INSERT OR REPLACE INTO api_cache (url, response, fetched_at) VALUES (?, ?, ?)",
        (url, json.dumps(data), int(time.time())),
    )
    conn.commit()
