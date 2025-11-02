from pydantic import BaseModel

from draft_analyst.analytics.champion_stats import ChampionStats, MatchupDelta


class CounterPickResult(BaseModel):
    champion: str
    avg_delta: float  # average matchup delta across all enemies
    matchups: list[MatchupDelta]
    # how many of the enemy matchups are favorable
    favorable_count: int
    total_enemy_matchups: int


class CounterPickAnalyzer:
    """Given enemy picks + user role, find champions with positive matchup deltas."""

    def __init__(self, stats: ChampionStats, role_champions: dict[str, list[str]] | None = None):
        self.stats = stats
        # optional: filter candidates by role
        # maps role -> list of champion names that play that role
        self.role_champions = role_champions or {}

    def analyze(
        self,
        enemy_picks: list[str],
        role: str | None = None,
        min_games: int = 3,
        limit: int = 15,
    ) -> list[CounterPickResult]:
        """Find the best counter-picks against the enemy team.

        For each candidate champion, compute their average matchup delta
        against all enemy picks. Champions who do well against more of the
        enemy team rank higher.
        """
        candidates = self._get_candidates(role)
        results = []

        for champ in candidates:
            # skip if they're already on the enemy team
            if champ in enemy_picks:
                continue

            matchups = []
            for enemy in enemy_picks:
                delta = self.stats.get_matchup_delta(champ, enemy)
                if delta and delta.games >= min_games:
                    matchups.append(delta)

            if not matchups:
                continue

            avg_delta = sum(m.delta for m in matchups) / len(matchups)
            favorable = sum(1 for m in matchups if m.delta > 0)

            results.append(CounterPickResult(
                champion=champ,
                avg_delta=avg_delta,
                matchups=matchups,
                favorable_count=favorable,
                total_enemy_matchups=len(matchups),
            ))

        # sort by avg delta, break ties by favorable count
        results.sort(key=lambda r: (r.avg_delta, r.favorable_count), reverse=True)
        return results[:limit]

    def _get_candidates(self, role: str | None) -> list[str]:
        if role and role in self.role_champions:
            return self.role_champions[role]
        return self.stats.all_champions()
