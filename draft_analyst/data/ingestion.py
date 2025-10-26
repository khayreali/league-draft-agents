import logging
from datetime import datetime

from draft_analyst.data.data_dragon import DataDragonClient
from draft_analyst.data.match_store import MatchStore
from draft_analyst.data.patch_scraper import PatchNotesScraper
from draft_analyst.data.riot_client import RiotClient

log = logging.getLogger(__name__)


class IngestionPipeline:
    """Orchestrates pulling matches + patch notes + champion data."""

    def __init__(self, riot: RiotClient, ddragon: DataDragonClient):
        self.riot = riot
        self.ddragon = ddragon
        self.match_store = MatchStore()
        self._scraper: PatchNotesScraper | None = None

    async def _get_scraper(self) -> PatchNotesScraper:
        if self._scraper is None:
            champ_names = await self.ddragon.get_champion_list()
            self._scraper = PatchNotesScraper(champion_names=champ_names)
        return self._scraper

    async def run(
        self,
        since: str,
        platforms: list[str],
        max_players_per_platform: int = 10,
        matches_per_player: int = 10,
        num_patches: int = 5,
    ) -> dict:
        """Run the full ingestion. Returns a summary dict."""
        start_epoch = int(datetime.fromisoformat(since).timestamp())

        # champion data
        version = await self.ddragon.get_latest_version()
        champs = await self.ddragon.get_champions(version)
        log.info(f"loaded {len(champs)} champions for {version}")

        # soloq matches from each platform
        total_matches = 0
        for platform in platforms:
            log.info(f"pulling high-elo matches from {platform}...")
            matches = await self.riot.fetch_high_elo_matches(
                platform=platform,
                start_time=start_epoch,
                max_players=max_players_per_platform,
                matches_per_player=matches_per_player,
            )
            new = self.match_store.store(matches)
            total_matches += new

        # patch notes
        scraper = await self._get_scraper()
        recent_patches = self._recent_patch_versions(version, num_patches)
        log.info(f"scraping patch notes for: {recent_patches}")
        notes = await scraper.fetch_recent(recent_patches, limit=num_patches)

        summary = {
            "champion_version": version,
            "champions_loaded": len(champs),
            "matches_ingested": total_matches,
            "total_matches_in_db": self.match_store.count(),
            "patch_notes_scraped": len(notes),
            "patches_with_notes": [n.patch for n in notes],
        }
        log.info(f"ingestion complete: {summary}")
        return summary

    def _recent_patch_versions(self, current: str, n: int) -> list[str]:
        """Generate the last N patch version strings from the current one.

        Riot patches go major.minor, minor increments each cycle.
        e.g. 16.7 -> 16.6 -> 16.5 -> ...
        When minor hits 1, the previous is (major-1).24ish but that's rare
        enough that we just stop there.
        """
        parts = current.split(".")
        major = int(parts[0])
        # strip any sub-patch like "16.7.1" -> 7
        minor = int(parts[1])

        patches = []
        for _ in range(n):
            patches.append(f"{major}.{minor}")
            minor -= 1
            if minor < 1:
                major -= 1
                minor = 24  # rough guess, patches usually go up to ~24
        return patches
