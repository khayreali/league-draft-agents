"""Builds the shared context (analytics + tools) from stored data."""
import logging

from draft_analyst.analytics.champion_stats import ChampionStats
from draft_analyst.analytics.counter_pick import CounterPickAnalyzer
from draft_analyst.analytics.pro_meta import ProMetaAnalyzer
from draft_analyst.analytics.synergy import SynergyCalculator
from draft_analyst.agents.tools import ToolExecutor
from draft_analyst.data.match_store import MatchStore

log = logging.getLogger(__name__)


def build_tool_executor(patch: str | None = None) -> ToolExecutor:
    """Load match data from the DB and build a ToolExecutor.

    If no real match data exists, generates a synthetic dataset so the
    system can still run end-to-end (useful for development/demo).
    """
    store = MatchStore()
    all_matches = store.get_by_patch(patch) if patch else []

    # if no matches for this patch, grab everything we have
    if not all_matches:
        soloq = store.get_soloq_matches()
        pro = store.get_pro_matches()
        all_matches = soloq + pro

    if not all_matches:
        log.warning("no match data in DB — generating synthetic data for demo")
        all_matches = _generate_synthetic_matches()

    champion_stats = ChampionStats(all_matches)
    pro_meta = ProMetaAnalyzer(all_matches)
    synergy_calc = SynergyCalculator(all_matches)
    counter_pick = CounterPickAnalyzer(champion_stats)

    log.info(f"built tools from {len(all_matches)} matches")
    return ToolExecutor(champion_stats, pro_meta, synergy_calc, counter_pick)


def _generate_synthetic_matches():
    """Generate fake matches so the system works without real API data.

    This is gross but it means you can run `draft recommend` without
    having a Riot API key or running ingest first. The eval should
    obviously use real data.
    """
    import random
    from draft_analyst.domain.models import MatchData

    random.seed(42)

    # champion pool roughly matching current meta
    top = ["Aatrox", "Gnar", "K'Sante", "Ambessa", "Jax", "Rumble", "Camille", "Renekton"]
    jng = ["LeeSin", "Viego", "Sejuani", "Rek'Sai", "Elise", "Graves", "Ivern", "Jarvan IV"]
    mid = ["Ahri", "Syndra", "Aurora", "Corki", "Twisted Fate", "Azir", "Orianna", "LeBlanc"]
    bot = ["Jinx", "Caitlyn", "Varus", "Kog'Maw", "Draven", "Zeri", "Aphelios", "Kai'Sa"]
    sup = ["Thresh", "Nautilus", "Lulu", "Leona", "Rell", "Maokai", "Braum", "Alistar"]

    # some synergy pairs that should win more often together
    synergy_boost = {
        ("Jinx", "Thresh"): 0.15,
        ("Aatrox", "Sejuani"): 0.1,
        ("Ahri", "LeeSin"): 0.1,
        ("Varus", "Nautilus"): 0.12,
        ("Caitlyn", "Lulu"): 0.1,
        ("Aurora", "Sejuani"): 0.15,
        ("Corki", "Rek'Sai"): 0.1,
        ("K'Sante", "Viego"): 0.1,
    }

    # some champs are just stronger right now
    strong_champs = {"Aatrox": 0.08, "Aurora": 0.07, "Jinx": 0.05, "Sejuani": 0.06,
                     "K'Sante": 0.06, "Nautilus": 0.05, "Corki": 0.07, "Varus": 0.05}

    matches = []
    for i in range(200):
        t1 = [random.choice(top), random.choice(jng), random.choice(mid),
              random.choice(bot), random.choice(sup)]
        t2 = [random.choice(top), random.choice(jng), random.choice(mid),
              random.choice(bot), random.choice(sup)]

        # base 50/50, then adjust for strength + synergy
        t1_bonus = sum(strong_champs.get(c, 0) for c in t1)
        t2_bonus = sum(strong_champs.get(c, 0) for c in t2)
        for (a, b), boost in synergy_boost.items():
            if a in t1 and b in t1:
                t1_bonus += boost
            if a in t2 and b in t2:
                t2_bonus += boost

        t1_wr = 0.5 + t1_bonus - t2_bonus
        t1_wins = random.random() < t1_wr

        is_pro = i < 50  # first 50 are "pro" matches
        winners = t1 if t1_wins else t2
        losers = t2 if t1_wins else t1

        matches.append(MatchData(
            match_id=f"SYNTH_{i:04d}",
            patch="16.7",
            region="na1",
            is_pro=is_pro,
            winning_team=winners,
            losing_team=losers,
            duration_seconds=random.randint(1200, 2400),
            timestamp=1712000000 + i * 600,
        ))

    log.info(f"generated {len(matches)} synthetic matches")
    return matches
