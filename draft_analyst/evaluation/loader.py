"""Loads eval scenarios from YAML."""
import logging
from pathlib import Path

import yaml

from draft_analyst.domain.models import DraftState, EvalScenario

log = logging.getLogger(__name__)


def load_scenarios(path: str | Path) -> list[EvalScenario]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"scenarios file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    scenarios = []
    for s in data.get("scenarios", []):
        ds = s["draft_state"]
        scenario = EvalScenario(
            name=s["name"],
            description=s.get("description", ""),
            draft_state=DraftState(
                patch=ds["patch"],
                user_role=ds["user_role"],
                user_team_picks=ds.get("user_team_picks", []),
                enemy_team_picks=ds.get("enemy_team_picks", []),
                bans=ds.get("bans", []),
                rank=ds.get("rank", "emerald+"),
            ),
            expected_good_picks=s.get("expected_good_picks", []),
            expected_bad_picks=s.get("expected_bad_picks", []),
            difficulty=s.get("difficulty", "medium"),
        )
        scenarios.append(scenario)

    log.info(f"loaded {len(scenarios)} scenarios from {path}")
    return scenarios
