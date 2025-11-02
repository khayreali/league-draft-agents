from collections import defaultdict
from pydantic import BaseModel

from draft_analyst.domain.models import MatchData


class ProPresence(BaseModel):
    champion: str
    picks: int
    wins: int
    win_rate: float
    pick_rate: float  # fraction of pro games this champ appears in
    # common teammates — which champs are drafted alongside this one most often
    common_teammates: list[tuple[str, int]]


class CompProfile(BaseModel):
    """A comp archetype this champion frequently appears in."""
    champion: str
    teammates: list[str]
    games: int
    wins: int


class ProMetaAnalyzer:
    """Analyzes pro match data for pick trends and composition patterns."""

    def __init__(self, matches: list[MatchData]):
        # only pro matches
        self.matches = [m for m in matches if m.is_pro]
        self._picks: dict[str, int] = defaultdict(int)
        self._wins: dict[str, int] = defaultdict(int)
        # track who gets drafted together
        self._pair_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._pair_wins: dict[tuple[str, str], int] = defaultdict(int)
        self._compute()

    def _compute(self):
        for m in self.matches:
            for team, won in [(m.winning_team, True), (m.losing_team, False)]:
                for champ in team:
                    self._picks[champ] += 1
                    if won:
                        self._wins[champ] += 1
                # pairwise co-occurrence within the team
                sorted_team = sorted(team)
                for i, a in enumerate(sorted_team):
                    for b in sorted_team[i + 1:]:
                        pair = (a, b)
                        self._pair_counts[pair] += 1
                        if won:
                            self._pair_wins[pair] += 1

    def get_presence(self, champion: str) -> ProPresence | None:
        picks = self._picks.get(champion, 0)
        if picks == 0:
            return None

        wins = self._wins.get(champion, 0)
        total_games = max(len(self.matches), 1)

        # find most common teammates
        teammate_counts: dict[str, int] = defaultdict(int)
        for (a, b), count in self._pair_counts.items():
            if a == champion:
                teammate_counts[b] += count
            elif b == champion:
                teammate_counts[a] += count

        top_mates = sorted(teammate_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return ProPresence(
            champion=champion,
            picks=picks,
            wins=wins,
            win_rate=wins / picks,
            pick_rate=picks / total_games,
            common_teammates=top_mates,
        )

    def top_picks(self, limit: int = 20) -> list[ProPresence]:
        results = []
        for champ in self._picks:
            pres = self.get_presence(champ)
            if pres:
                results.append(pres)
        results.sort(key=lambda p: p.picks, reverse=True)
        return results[:limit]

    def trending_picks(self, min_picks: int = 3, min_wr: float = 0.5) -> list[ProPresence]:
        """Champions with high pick counts AND winning records in pro."""
        results = []
        for champ in self._picks:
            pres = self.get_presence(champ)
            if pres and pres.picks >= min_picks and pres.win_rate >= min_wr:
                results.append(pres)
        results.sort(key=lambda p: (p.win_rate, p.picks), reverse=True)
        return results

    def get_comp_profiles(self, champion: str, min_games: int = 2) -> list[CompProfile]:
        """Find recurring team compositions this champion appears in."""
        # group by full team composition
        comp_map: dict[tuple[str, ...], list[bool]] = defaultdict(list)
        for m in self.matches:
            for team, won in [(m.winning_team, True), (m.losing_team, False)]:
                if champion in team:
                    key = tuple(sorted(team))
                    comp_map[key].append(won)

        profiles = []
        for comp, outcomes in comp_map.items():
            if len(outcomes) >= min_games:
                profiles.append(CompProfile(
                    champion=champion,
                    teammates=[c for c in comp if c != champion],
                    games=len(outcomes),
                    wins=sum(outcomes),
                ))
        profiles.sort(key=lambda p: p.games, reverse=True)
        return profiles
