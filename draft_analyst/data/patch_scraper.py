import json
import logging
import re
import sqlite3
import time
from pathlib import Path

import httpx
import yaml

from draft_analyst.config import PROJECT_ROOT
from draft_analyst.data.cache import get_connection
from draft_analyst.domain.models import PatchNote

log = logging.getLogger(__name__)

# i tried scraping the league wiki first but it 403s automated requests,
# and the official site is JS-rendered garbage. so the primary source is
# local YAML files in eval/patch_notes/ that i curate myself. the web
# scraper is still here as a fallback if the wiki ever cooperates.
WIKI_URL = "https://wiki.leagueoflegends.com/en-us/Patch_{patch}"
PATCH_NOTES_DIR = PROJECT_ROOT / "eval" / "patch_notes"


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _extract_champion_mentions(text: str, champion_names: list[str]) -> list[str]:
    text_lower = text.lower()
    return [name for name in champion_names if name.lower() in text_lower]


class PatchNotesScraper:
    def __init__(self, conn: sqlite3.Connection | None = None, champion_names: list[str] | None = None):
        self.db = conn or get_connection()
        self._ensure_table()
        self.champion_names = champion_names or []

    def _ensure_table(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS patch_notes (
                patch TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                champions_mentioned JSON,
                fetched_at INTEGER NOT NULL
            )
        """)
        self.db.commit()

    def get_cached(self, patch: str) -> PatchNote | None:
        row = self.db.execute(
            "SELECT content, champions_mentioned FROM patch_notes WHERE patch = ?",
            (patch,)
        ).fetchone()
        if row:
            champs = json.loads(row["champions_mentioned"]) if row["champions_mentioned"] else []
            return PatchNote(patch=patch, content=row["content"], champions_mentioned=champs)
        return None

    async def fetch_patch(self, patch: str) -> PatchNote | None:
        """Get patch notes: check cache -> local files -> web scrape."""
        cached = self.get_cached(patch)
        if cached:
            log.info(f"patch {patch} already cached")
            return cached

        # try local YAML first (the reliable path)
        note = self._load_local(patch)
        if note:
            self._save(note)
            return note

        # fall back to web scraping (unreliable but worth trying)
        note = await self._scrape_web(patch)
        if note:
            self._save(note)
            return note

        log.warning(f"no patch notes found for {patch}")
        return None

    def _load_local(self, patch: str) -> PatchNote | None:
        """Load from eval/patch_notes/{patch}.yaml if it exists."""
        path = PATCH_NOTES_DIR / f"{patch}.yaml"
        if not path.exists():
            return None

        log.info(f"loading patch notes from {path}")
        with open(path) as f:
            data = yaml.safe_load(f)

        content = data.get("content", "")
        champs = data.get("champions_mentioned", [])
        if not champs and self.champion_names:
            champs = _extract_champion_mentions(content, self.champion_names)

        return PatchNote(patch=patch, content=content, champions_mentioned=champs)

    async def _scrape_web(self, patch: str) -> PatchNote | None:
        url = WIKI_URL.format(patch=patch)
        log.info(f"trying web scrape: {url}")

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
            except httpx.HTTPError as e:
                log.warning(f"failed to fetch patch {patch}: {e}")
                return None

            if resp.status_code != 200:
                log.warning(f"patch {patch} returned {resp.status_code}")
                return None

        content = _strip_html(resp.text)
        if len(content) < 200:
            log.warning(f"patch {patch} content too short, probably a bad page")
            return None

        champs = _extract_champion_mentions(content, self.champion_names)
        return PatchNote(patch=patch, content=content, champions_mentioned=champs)

    def _save(self, note: PatchNote):
        self.db.execute(
            """INSERT OR REPLACE INTO patch_notes
               (patch, content, champions_mentioned, fetched_at)
               VALUES (?, ?, ?, ?)""",
            (note.patch, note.content, json.dumps(note.champions_mentioned),
             int(time.time())),
        )
        self.db.commit()
        log.info(f"saved patch {note.patch} ({len(note.content)} chars, {len(note.champions_mentioned)} champs)")

    async def fetch_recent(self, patches: list[str], limit: int = 5) -> list[PatchNote]:
        notes = []
        for patch in patches[:limit]:
            note = await self.fetch_patch(patch)
            if note:
                notes.append(note)
        return notes

    def get_all_cached(self) -> list[PatchNote]:
        rows = self.db.execute(
            "SELECT patch, content, champions_mentioned FROM patch_notes ORDER BY patch DESC"
        ).fetchall()
        return [
            PatchNote(
                patch=r["patch"],
                content=r["content"],
                champions_mentioned=json.loads(r["champions_mentioned"]) if r["champions_mentioned"] else [],
            )
            for r in rows
        ]
