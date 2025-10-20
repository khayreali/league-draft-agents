import json
import logging

import httpx

from draft_analyst.data.cache import get_connection, init_db, cache_get, cache_set
from draft_analyst.domain.models import Champion

log = logging.getLogger(__name__)

DDRAGON_BASE = "https://ddragon.leagueoflegends.com"


class DataDragonClient:
    """Fetches static champion/item/patch data from Data Dragon. No rate limits."""

    def __init__(self):
        self.db = get_connection()
        init_db(self.db)
        self._versions: list[str] | None = None

    async def get_latest_version(self) -> str:
        if self._versions is None:
            self._versions = await self._fetch_versions()
        return self._versions[0]

    async def get_versions(self) -> list[str]:
        if self._versions is None:
            self._versions = await self._fetch_versions()
        return self._versions

    async def _fetch_versions(self) -> list[str]:
        url = f"{DDRAGON_BASE}/api/versions.json"
        cached = cache_get(self.db, url)
        if cached:
            return cached

        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            versions = resp.json()
            cache_set(self.db, url, versions)
            return versions

    async def get_champions(self, version: str | None = None) -> dict[str, Champion]:
        """Returns {champion_id: Champion} for the given patch version."""
        if version is None:
            version = await self.get_latest_version()

        # check sqlite first
        row = self.db.execute(
            "SELECT data FROM champion_data WHERE patch = ?", (version,)
        ).fetchone()
        if row:
            raw = json.loads(row["data"])
            return {k: Champion(**v) for k, v in raw.items()}

        url = f"{DDRAGON_BASE}/cdn/{version}/data/en_US/champion.json"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()["data"]

        champs = {}
        serializable = {}
        for key, val in data.items():
            c = Champion(
                id=val["id"],
                name=val["name"],
                key=int(val["key"]),
                tags=val.get("tags", []),
            )
            champs[key] = c
            serializable[key] = c.model_dump()

        import time
        self.db.execute(
            "INSERT OR REPLACE INTO champion_data (patch, data, fetched_at) VALUES (?, ?, ?)",
            (version, json.dumps(serializable), int(time.time())),
        )
        self.db.commit()
        log.info(f"cached {len(champs)} champions for patch {version}")
        return champs

    async def get_champion_list(self, version: str | None = None) -> list[str]:
        """Just the champion names."""
        champs = await self.get_champions(version)
        return [c.name for c in champs.values()]
