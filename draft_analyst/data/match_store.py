import json
import logging
import sqlite3
import time

from draft_analyst.data.cache import get_connection, init_db
from draft_analyst.domain.models import MatchData

log = logging.getLogger(__name__)


class MatchStore:
    """SQLite-backed store for match data. Wraps the matches table."""

    def __init__(self, conn: sqlite3.Connection | None = None):
        self.db = conn or get_connection()
        init_db(self.db)

    def store(self, matches: list[MatchData]):
        inserted = 0
        for m in matches:
            cur = self.db.execute(
                """INSERT OR IGNORE INTO matches
                   (match_id, region, patch, is_pro, data, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (m.match_id, m.region, m.patch, int(m.is_pro),
                 m.model_dump_json(), int(time.time())),
            )
            inserted += cur.rowcount
        self.db.commit()
        log.info(f"stored {inserted} new matches ({len(matches) - inserted} already existed)")
        return inserted

    def get_by_patch(self, patch: str, is_pro: bool | None = None) -> list[MatchData]:
        if is_pro is not None:
            rows = self.db.execute(
                "SELECT data FROM matches WHERE patch = ? AND is_pro = ?",
                (patch, int(is_pro)),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT data FROM matches WHERE patch = ?", (patch,)
            ).fetchall()
        return [MatchData(**json.loads(r["data"])) for r in rows]

    def get_pro_matches(self, patch: str | None = None) -> list[MatchData]:
        if patch:
            rows = self.db.execute(
                "SELECT data FROM matches WHERE is_pro = 1 AND patch = ?", (patch,)
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT data FROM matches WHERE is_pro = 1"
            ).fetchall()
        return [MatchData(**json.loads(r["data"])) for r in rows]

    def get_soloq_matches(self, patch: str | None = None) -> list[MatchData]:
        if patch:
            rows = self.db.execute(
                "SELECT data FROM matches WHERE is_pro = 0 AND patch = ?", (patch,)
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT data FROM matches WHERE is_pro = 0"
            ).fetchall()
        return [MatchData(**json.loads(r["data"])) for r in rows]

    def get_all_patches(self) -> list[str]:
        rows = self.db.execute(
            "SELECT DISTINCT patch FROM matches ORDER BY patch DESC"
        ).fetchall()
        return [r["patch"] for r in rows]

    def count(self, is_pro: bool | None = None) -> int:
        if is_pro is not None:
            row = self.db.execute(
                "SELECT COUNT(*) as n FROM matches WHERE is_pro = ?", (int(is_pro),)
            ).fetchone()
        else:
            row = self.db.execute("SELECT COUNT(*) as n FROM matches").fetchone()
        return row["n"]

    def has_match(self, match_id: str) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM matches WHERE match_id = ?", (match_id,)
        ).fetchone()
        return row is not None
