"""Re-run only the errored scenarios from comparison_v1.json and merge results."""
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from draft_analyst.agents.baseline import SingleAgentBaseline
from draft_analyst.agents.coordinator import LangGraphCoordinator
from draft_analyst.agents.context import build_tool_executor
from draft_analyst.config import DEFAULT_AGENT_MODEL
from draft_analyst.evaluation.evaluator import Evaluator
from draft_analyst.evaluation.loader import load_scenarios
from draft_analyst.llm_client import get_llm_client

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

V1_PATH = Path("eval/results/comparison_v1.json")
V2_PATH = Path("eval/results/comparison_v2.json")
SCENARIOS_PATH = Path("eval/scenarios.yaml")
DELAY_BETWEEN = 20  # seconds between scenarios to avoid rate limits


def find_errored(v1_data):
    errored = []
    for r in v1_data["multi_agent"]:
        if r["system_name"] == "error" or not r["recommendations"]:
            errored.append(r["scenario_name"])
    return errored


def main():
    with open(V1_PATH) as f:
        v1 = json.load(f)

    errored_names = find_errored(v1)
    if not errored_names:
        print("no errored scenarios found, nothing to rerun")
        return

    print(f"errored scenarios to rerun: {errored_names}")

    all_scenarios = load_scenarios(SCENARIOS_PATH)
    rerun_scenarios = [s for s in all_scenarios if s.name in errored_names]
    print(f"loaded {len(rerun_scenarios)} scenarios for rerun")

    tool_executor = build_tool_executor()
    llm = get_llm_client()
    multi_agent = LangGraphCoordinator(llm, DEFAULT_AGENT_MODEL, tool_executor)

    evaluator = Evaluator(multi_agent.run)
    results = evaluator.evaluate(rerun_scenarios, delay_between=DELAY_BETWEEN)

    # check for new errors
    still_errored = [r for r in results if r.system_name == "error" or not r.recommendations]
    if still_errored:
        print(f"\nWARNING: {len(still_errored)} scenarios still errored:")
        for r in still_errored:
            print(f"  {r.scenario_name}")

    # merge into v1 data
    rerun_map = {r.scenario_name: r for r in results}
    merged_multi = []
    for orig in v1["multi_agent"]:
        name = orig["scenario_name"]
        if name in rerun_map:
            r = rerun_map[name]
            merged_multi.append(r.model_dump())
        else:
            merged_multi.append(orig)

    v2 = {
        "baseline": v1["baseline"],
        "multi_agent": merged_multi,
    }

    # recompute summaries
    from draft_analyst.domain.models import EvalResult, Recommendation
    def _to_eval_results(entries):
        results = []
        for e in entries:
            recs = [Recommendation(**r) if isinstance(r, dict) else r for r in e.get("recommendations", [])]
            results.append(EvalResult(
                scenario_name=e["scenario_name"],
                system_name=e["system_name"],
                recommendations=recs,
                top_pick_quality=e["top_pick_quality"],
                top_3_recall=e["top_3_recall"],
                bad_pick_avoidance=e["bad_pick_avoidance"],
                reasoning_quality=e.get("reasoning_quality"),
                latency_ms=e["latency_ms"],
                tool_call_count=e["tool_call_count"],
            ))
        return results

    from draft_analyst.evaluation.evaluator import aggregate_results
    v2["baseline_summary"] = aggregate_results(_to_eval_results(v2["baseline"]))
    v2["multi_agent_summary"] = aggregate_results(_to_eval_results(v2["multi_agent"]))

    with open(V2_PATH, "w") as f:
        json.dump(v2, f, indent=2, default=str)
    print(f"\nmerged results saved to {V2_PATH}")

    # quick summary
    ms = v2["multi_agent_summary"]
    bs = v2["baseline_summary"]
    print(f"\nv2 overall:")
    print(f"  baseline:    top1={bs['top_pick_accuracy']:.1%} recall={bs['avg_top3_recall']:.1%} bad_avoid={bs['bad_pick_avoidance']:.1%}")
    print(f"  multi-agent: top1={ms['top_pick_accuracy']:.1%} recall={ms['avg_top3_recall']:.1%} bad_avoid={ms['bad_pick_avoidance']:.1%}")

    # verify no errors remain
    error_count = sum(1 for e in v2["multi_agent"] if e["system_name"] == "error" or not e.get("recommendations"))
    print(f"\nremaining errors: {error_count}")


if __name__ == "__main__":
    main()
