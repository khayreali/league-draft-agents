import pytest

from draft_analyst.analytics.champion_stats import ChampionStats, wilson_interval
from draft_analyst.analytics.synergy import SynergyCalculator
from draft_analyst.analytics.counter_pick import CounterPickAnalyzer
from draft_analyst.analytics.pro_meta import ProMetaAnalyzer
from draft_analyst.domain.models import MatchData


def _make_match(mid, winners, losers, is_pro=False):
    return MatchData(
        match_id=mid, patch="16.7", region="na1", is_pro=is_pro,
        winning_team=winners, losing_team=losers,
        duration_seconds=1800, timestamp=1712000000,
    )


MATCHES = [
    _make_match("m1", ["Aatrox", "LeeSin", "Ahri", "Jinx", "Thresh"],
                       ["Gnar", "Viego", "Syndra", "Caitlyn", "Lulu"]),
    _make_match("m2", ["Aatrox", "Sejuani", "Ahri", "Varus", "Nautilus"],
                       ["Gnar", "LeeSin", "Syndra", "Jinx", "Thresh"]),
    _make_match("m3", ["Gnar", "Viego", "Aurora", "Caitlyn", "Lulu"],
                       ["Aatrox", "Sejuani", "Ahri", "Varus", "Nautilus"]),
    _make_match("m4", ["Aatrox", "LeeSin", "Aurora", "Jinx", "Nautilus"],
                       ["Gnar", "Sejuani", "Syndra", "Caitlyn", "Thresh"]),
    _make_match("m5", ["Gnar", "Viego", "Syndra", "Jinx", "Lulu"],
                       ["Aatrox", "LeeSin", "Ahri", "Caitlyn", "Thresh"]),
]


def test_wilson_zero_games():
    lo, hi = wilson_interval(0, 0)
    assert lo == 0.0
    assert hi == 0.0


def test_wilson_perfect_record_small_sample():
    lo, hi = wilson_interval(3, 3)
    # perfect record but only 3 games — lower bound should be well below 1.0
    assert lo < 0.5
    assert hi == 1.0


def test_wilson_large_sample():
    lo, hi = wilson_interval(500, 1000)
    # 50% WR with 1000 games — tight interval around 0.5
    assert 0.46 < lo < 0.50
    assert 0.50 < hi < 0.54


def test_champion_stats_basic():
    cs = ChampionStats(MATCHES)
    aatrox = cs.get_stats("Aatrox")
    assert aatrox is not None
    assert aatrox.games == 5  # appears in all 5 matches
    assert aatrox.wins == 3
    assert abs(aatrox.win_rate - 0.6) < 0.01


def test_champion_stats_unknown():
    cs = ChampionStats(MATCHES)
    assert cs.get_stats("Teemo") is None


def test_top_by_win_rate():
    cs = ChampionStats(MATCHES)
    # min_games=1 so we don't filter anyone out
    top = cs.top_by_win_rate(min_games=1, limit=5)
    assert len(top) > 0
    # should be sorted by wilson lower bound (descending)
    for i in range(len(top) - 1):
        assert top[i].wr_lower >= top[i + 1].wr_lower


def test_matchup_delta():
    cs = ChampionStats(MATCHES)
    delta = cs.get_matchup_delta("Aatrox", "Gnar")
    assert delta is not None
    # aatrox and gnar are on opposite teams in every match
    assert delta.games > 0


def test_synergy_basic():
    sc = SynergyCalculator(MATCHES)
    # aatrox and ahri are teammates in m1, m2, m3(losing), m5(losing)
    score = sc.get_synergy("Aatrox", "Ahri")
    assert score is not None
    assert score.games_together > 0


def test_synergy_candidate():
    sc = SynergyCalculator(MATCHES)
    # how well does Jinx synergize with a team of [Aatrox, LeeSin]?
    avg = sc.candidate_synergy("Jinx", ["Aatrox", "LeeSin"])
    assert isinstance(avg, float)


def test_counter_pick_basic():
    cs = ChampionStats(MATCHES)
    cp = CounterPickAnalyzer(cs)
    results = cp.analyze(enemy_picks=["Gnar", "Syndra"], min_games=1, limit=5)
    assert len(results) > 0
    # none of the results should include Gnar or Syndra themselves
    for r in results:
        assert r.champion not in ["Gnar", "Syndra"]


PRO_MATCHES = [
    _make_match("p1", ["Aatrox", "Sejuani", "Ahri", "Varus", "Nautilus"],
                       ["Gnar", "LeeSin", "Syndra", "Jinx", "Thresh"], is_pro=True),
    _make_match("p2", ["Aatrox", "LeeSin", "Aurora", "Jinx", "Nautilus"],
                       ["Gnar", "Sejuani", "Syndra", "Caitlyn", "Thresh"], is_pro=True),
    _make_match("p3", ["Gnar", "Viego", "Ahri", "Caitlyn", "Lulu"],
                       ["Aatrox", "Sejuani", "Syndra", "Varus", "Nautilus"], is_pro=True),
]


def test_pro_meta_filters_non_pro():
    mixed = MATCHES + PRO_MATCHES  # MATCHES are not pro
    pma = ProMetaAnalyzer(mixed)
    # should only use the 3 pro matches
    assert len(pma.matches) == 3


def test_pro_top_picks():
    pma = ProMetaAnalyzer(PRO_MATCHES)
    top = pma.top_picks(limit=5)
    assert len(top) > 0
    # aatrox appears in all 3 pro matches
    aatrox = pma.get_presence("Aatrox")
    assert aatrox is not None
    assert aatrox.picks == 3
