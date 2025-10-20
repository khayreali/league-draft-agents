import asyncio
import json
import logging
import time

import httpx

from draft_analyst.config import (
    RIOT_API_KEY,
    RIOT_RATE_LIMIT_PER_SECOND,
    RIOT_RATE_LIMIT_PER_2MIN,
)
from draft_analyst.data.cache import get_connection, init_db, cache_get, cache_set
from draft_analyst.data.rate_limiter import RiotRateLimiter
from draft_analyst.domain.models import MatchData

log = logging.getLogger(__name__)

# platform -> regional routing for match-v5
PLATFORM_TO_REGION = {
    "na1": "americas",
    "br1": "americas",
    "la1": "americas",
    "la2": "americas",
    "euw1": "europe",
    "eun1": "europe",
    "tr1": "europe",
    "ru": "europe",
    "kr": "asia",
    "jp1": "asia",
}


class RiotClient:
    """Async client for the Riot Games API with rate limiting and caching."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or RIOT_API_KEY
        if not self.api_key:
            raise ValueError("RIOT_API_KEY not set — check your .env")
        self.limiter = RiotRateLimiter(
            per_second=RIOT_RATE_LIMIT_PER_SECOND,
            per_2min=RIOT_RATE_LIMIT_PER_2MIN,
        )
        self.db = get_connection()
        init_db(self.db)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={"X-Riot-Token": self.api_key},
                timeout=30.0,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, url: str, use_cache: bool = True) -> dict:
        if use_cache:
            cached = cache_get(self.db, url)
            if cached is not None:
                return cached

        await self.limiter.acquire()
        client = await self._get_client()

        for attempt in range(3):
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if use_cache:
                    cache_set(self.db, url, data)
                return data
            elif resp.status_code == 429:
                # rate limited — back off using retry-after header
                retry_after = int(resp.headers.get("Retry-After", 5))
                log.warning(f"429 rate limited, waiting {retry_after}s (attempt {attempt + 1})")
                await asyncio.sleep(retry_after)
            elif resp.status_code == 403:
                raise PermissionError(f"API key rejected (403) for {url}")
            else:
                log.error(f"riot api {resp.status_code}: {url}")
                raise httpx.HTTPStatusError(
                    f"unexpected {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )

        raise RuntimeError(f"failed after 3 retries: {url}")


    async def get_challenger_players(self, platform: str = "na1", queue: str = "RANKED_SOLO_5x5") -> list[str]:
        """Get summoner IDs of challenger players."""
        url = f"https://{platform}.api.riotgames.com/lol/league/v4/challengerleagues/by-queue/{queue}"
        data = await self._request(url)
        return [entry["summonerId"] for entry in data.get("entries", [])]

    async def get_grandmaster_players(self, platform: str = "na1", queue: str = "RANKED_SOLO_5x5") -> list[str]:
        url = f"https://{platform}.api.riotgames.com/lol/league/v4/grandmasterleagues/by-queue/{queue}"
        data = await self._request(url)
        return [entry["summonerId"] for entry in data.get("entries", [])]

    async def get_puuid_by_summoner_id(self, summoner_id: str, platform: str = "na1") -> str:
        url = f"https://{platform}.api.riotgames.com/lol/summoner/v4/summoners/{summoner_id}"
        data = await self._request(url)
        return data["puuid"]


    async def get_match_ids(
        self,
        puuid: str,
        platform: str = "na1",
        count: int = 20,
        start_time: int | None = None,
        queue: int = 420,  # ranked solo
    ) -> list[str]:
        region = PLATFORM_TO_REGION[platform]
        url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
        params = [f"count={count}", f"queue={queue}"]
        if start_time:
            params.append(f"startTime={start_time}")
        url += "?" + "&".join(params)
        return await self._request(url)

    async def get_match(self, match_id: str, platform: str = "na1") -> dict:
        region = PLATFORM_TO_REGION[platform]
        url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        return await self._request(url)


    def parse_match(self, raw: dict, region: str, is_pro: bool = False) -> MatchData | None:
        """Turn raw match JSON into our MatchData model. Returns None for remakes."""
        info = raw.get("info", {})
        if info.get("gameDuration", 0) < 300:
            return None  # remake

        participants = info.get("participants", [])
        winners = []
        losers = []
        for p in participants:
            champ = p.get("championName", "Unknown")
            if p.get("win"):
                winners.append(champ)
            else:
                losers.append(champ)

        patch_str = info.get("gameVersion", "")
        # gameVersion is like "14.5.123.456", we just want "14.5"
        parts = patch_str.split(".")
        patch = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else patch_str

        return MatchData(
            match_id=raw["metadata"]["matchId"],
            patch=patch,
            region=region,
            is_pro=is_pro,
            winning_team=winners,
            losing_team=losers,
            duration_seconds=info.get("gameDuration", 0),
            timestamp=info.get("gameCreation", 0),
        )

    async def fetch_high_elo_matches(
        self,
        platform: str = "na1",
        start_time: int | None = None,
        max_players: int = 10,
        matches_per_player: int = 10,
    ) -> list[MatchData]:
        """Pull recent ranked matches from challenger/GM players."""
        log.info(f"fetching high-elo players from {platform}...")
        summoner_ids = await self.get_challenger_players(platform)
        summoner_ids = summoner_ids[:max_players]

        all_matches = []
        seen_ids = set()

        for sid in summoner_ids:
            try:
                puuid = await self.get_puuid_by_summoner_id(sid, platform)
                match_ids = await self.get_match_ids(
                    puuid, platform,
                    count=matches_per_player,
                    start_time=start_time,
                )
                for mid in match_ids:
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    raw = await self.get_match(mid, platform)
                    parsed = self.parse_match(raw, platform)
                    if parsed:
                        all_matches.append(parsed)
            except Exception as e:
                log.warning(f"skipping summoner {sid}: {e}")
                continue

        log.info(f"fetched {len(all_matches)} matches from {platform}")
        return all_matches

    def store_matches(self, matches: list[MatchData]):
        """Write parsed matches to the cache DB."""
        for m in matches:
            self.db.execute(
                """INSERT OR IGNORE INTO matches (match_id, region, patch, is_pro, data, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (m.match_id, m.region, m.patch, int(m.is_pro), m.model_dump_json(), int(time.time())),
            )
        self.db.commit()
        log.info(f"stored {len(matches)} matches")
