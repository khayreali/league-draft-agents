from collections import defaultdict
from pydantic import BaseModel

from draft_analyst.domain.models import MatchData


class SynergyScore(BaseModel):
    champion_a: str
    champion_b: str
    games_together: int
    wins_together: int
    wr_together: float
    # individual win rates for comparison
    wr_a_solo: float
    wr_b_solo: float
    # positive synergy means they win more together than you'd expect
    synergy_delta: float


class SynergyCalculator:
    """Computes pairwise synergy from co-occurrence win rates.

    The idea: if champ A wins 50% overall and champ B wins 50% overall,
    but they win 60% when on the same team, that's a +10% synergy.
    Naive but it works for finding combos that overperform.
    """

    def __init__(self, matches: list[MatchData]):
        self.matches = matches
        self._solo_wins: dict[str, int] = defaultdict(int)
        self._solo_games: dict[str, int] = defaultdict(int)
        self._pair_wins: dict[tuple[str, str], int] = defaultdict(int)
        self._pair_games: dict[tuple[str, str], int] = defaultdict(int)
        self._compute()

    def _compute(self):
        for m in self.matches:
            for team, won in [(m.winning_team, True), (m.losing_team, False)]:
                for champ in team:
                    self._solo_games[champ] += 1
                    if won:
                        self._solo_wins[champ] += 1

                sorted_team = sorted(team)
                for i, a in enumerate(sorted_team):
                    for b in sorted_team[i + 1:]:
                        pair = (a, b)
                        self._pair_games[pair] += 1
                        if won:
                            self._pair_wins[pair] += 1

    def _solo_wr(self, champ: str) -> float:
        games = self._solo_games.get(champ, 0)
        if games == 0:
            return 0.5
        return self._solo_wins.get(champ, 0) / games

    def _make_pair(self, a: str, b: str) -> tuple[str, str]:
        return (a, b) if a <= b else (b, a)

    def get_synergy(self, champ_a: str, champ_b: str) -> SynergyScore | None:
        pair = self._make_pair(champ_a, champ_b)
        games = self._pair_games.get(pair, 0)
        if games == 0:
            return None

        wins = self._pair_wins.get(pair, 0)
        wr_together = wins / games
        wr_a = self._solo_wr(champ_a)
        wr_b = self._solo_wr(champ_b)

        # expected WR if independent — just average of their solo WRs
        # (this is a simplification but close enough)
        expected = (wr_a + wr_b) / 2
        delta = wr_together - expected

        return SynergyScore(
            champion_a=champ_a,
            champion_b=champ_b,
            games_together=games,
            wins_together=wins,
            wr_together=wr_together,
            wr_a_solo=wr_a,
            wr_b_solo=wr_b,
            synergy_delta=delta,
        )

    def team_synergy(self, team: list[str]) -> list[SynergyScore]:
        """Get all pairwise synergies for a partial team comp."""
        scores = []
        sorted_team = sorted(team)
        for i, a in enumerate(sorted_team):
            for b in sorted_team[i + 1:]:
                score = self.get_synergy(a, b)
                if score:
                    scores.append(score)
        return scores

    def best_partners(self, champion: str, min_games: int = 3, limit: int = 10) -> list[SynergyScore]:
        """Find champions with the highest synergy with the given champ."""
        results = []
        for other in self._solo_games:
            if other == champion:
                continue
            score = self.get_synergy(champion, other)
            if score and score.games_together >= min_games:
                results.append(score)
        results.sort(key=lambda s: s.synergy_delta, reverse=True)
        return results[:limit]

    def candidate_synergy(self, candidate: str, existing_team: list[str]) -> float:
        """Average synergy delta between a candidate pick and the existing team."""
        deltas = []
        for teammate in existing_team:
            score = self.get_synergy(candidate, teammate)
            if score:
                deltas.append(score.synergy_delta)
        return sum(deltas) / len(deltas) if deltas else 0.0
