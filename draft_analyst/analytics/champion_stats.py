import math
from collections import defaultdict
from pydantic import BaseModel

from draft_analyst.domain.models import MatchData


class ChampStats(BaseModel):
    champion: str
    games: int
    wins: int
    win_rate: float
    pick_rate: float
    # wilson score 95% CI lower bound — useful for ranking with small samples
    wr_lower: float
    wr_upper: float


class MatchupDelta(BaseModel):
    champion: str
    opponent: str
    games: int
    win_rate_vs: float
    baseline_wr: float
    delta: float  # positive = does better than usual against this opponent


def wilson_interval(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Way better than naive p +/- z*sqrt(p(1-p)/n) for small samples.
    Returns (lower, upper) bounds.
    """
    if total == 0:
        return 0.0, 0.0
    p = wins / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return max(0.0, center - spread), min(1.0, center + spread)


class ChampionStats:
    """Computes win/pick/ban rates from match data."""

    def __init__(self, matches: list[MatchData]):
        self.matches = matches
        self._wins: dict[str, int] = defaultdict(int)
        self._games: dict[str, int] = defaultdict(int)
        self._compute()

    def _compute(self):
        for m in self.matches:
            for champ in m.winning_team:
                self._wins[champ] += 1
                self._games[champ] += 1
            for champ in m.losing_team:
                self._games[champ] += 1

    def get_stats(self, champion: str) -> ChampStats | None:
        games = self._games.get(champion, 0)
        if games == 0:
            return None
        wins = self._wins.get(champion, 0)
        wr = wins / games
        lower, upper = wilson_interval(wins, games)
        return ChampStats(
            champion=champion,
            games=games,
            wins=wins,
            win_rate=wr,
            pick_rate=games / max(len(self.matches), 1),
            wr_lower=lower,
            wr_upper=upper,
        )

    def top_by_win_rate(self, min_games: int = 5, limit: int = 20) -> list[ChampStats]:
        """Rank champions by wilson lower bound (not raw WR — punishes small samples)."""
        results = []
        for champ in self._games:
            stats = self.get_stats(champ)
            if stats and stats.games >= min_games:
                results.append(stats)
        results.sort(key=lambda s: s.wr_lower, reverse=True)
        return results[:limit]

    def all_champions(self) -> list[str]:
        return list(self._games.keys())

    def get_matchup_delta(self, champion: str, opponent: str) -> MatchupDelta | None:
        """How does `champion` do when `opponent` is on the enemy team?"""
        baseline = self.get_stats(champion)
        if not baseline:
            return None

        wins_vs = 0
        games_vs = 0
        for m in self.matches:
            if champion in m.winning_team and opponent in m.losing_team:
                wins_vs += 1
                games_vs += 1
            elif champion in m.losing_team and opponent in m.winning_team:
                games_vs += 1

        if games_vs == 0:
            return None

        wr_vs = wins_vs / games_vs
        return MatchupDelta(
            champion=champion,
            opponent=opponent,
            games=games_vs,
            win_rate_vs=wr_vs,
            baseline_wr=baseline.win_rate,
            delta=wr_vs - baseline.win_rate,
        )
