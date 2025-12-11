"""Evaluator — runs a system against an eval set and scores it."""
import json
import logging
import time

from draft_analyst.domain.models import AgentOutput, EvalResult, EvalScenario

log = logging.getLogger(__name__)


def score_output(
    scenario: EvalScenario,
    output: AgentOutput,
    latency_ms: float,
) -> EvalResult:
    """Score a system's output against a scenario's expected picks."""
    recs = output.recommendations
    rec_names = [r.champion for r in recs]

    good = set(scenario.expected_good_picks)
    bad = set(scenario.expected_bad_picks)

    # top pick quality: is the #1 recommendation a good pick?
    top_pick_quality = rec_names[0] in good if rec_names else False

    # top 3 recall: what fraction of expected good picks are in the top 3?
    top_3 = set(rec_names[:3])
    if good:
        top_3_recall = len(top_3 & good) / len(good)
    else:
        top_3_recall = 1.0

    # bad pick avoidance: did we avoid recommending any bad picks?
    recommended_bad = set(rec_names[:5]) & bad
    bad_pick_avoidance = len(recommended_bad) == 0

    return EvalResult(
        scenario_name=scenario.name,
        system_name=output.agent_name,
        recommendations=recs,
        top_pick_quality=top_pick_quality,
        top_3_recall=top_3_recall,
        bad_pick_avoidance=bad_pick_avoidance,
        reasoning_quality=None,  # TODO: LLM-as-judge
        latency_ms=latency_ms,
        tool_call_count=output.tool_calls_made,
    )


class Evaluator:
    """Runs a system against eval scenarios and collects results."""

    def __init__(self, run_fn):
        """run_fn: callable that takes DraftState and returns AgentOutput."""
        self.run_fn = run_fn

    def evaluate(self, scenarios: list[EvalScenario], delay_between: float = 0) -> list[EvalResult]:
        results = []
        for i, scenario in enumerate(scenarios):
            if delay_between and i > 0:
                log.info(f"sleeping {delay_between}s between scenarios...")
                time.sleep(delay_between)

            log.info(f"evaluating: {scenario.name} ({scenario.difficulty})")
            start = time.time()
            try:
                output = self.run_fn(scenario.draft_state)
            except Exception as e:
                log.error(f"scenario {scenario.name} failed: {e}")
                output = AgentOutput(
                    agent_name="error",
                    recommendations=[],
                    raw_reasoning=str(e),
                    tool_calls_made=0,
                )
            elapsed = (time.time() - start) * 1000

            result = score_output(scenario, output, elapsed)
            results.append(result)

            status = "PASS" if result.top_pick_quality else "MISS"
            log.info(
                f"  {status} | top3_recall={result.top_3_recall:.2f} "
                f"| bad_avoid={result.bad_pick_avoidance} "
                f"| {result.latency_ms:.0f}ms"
            )

        return results


def aggregate_results(results: list[EvalResult]) -> dict:
    """Compute aggregate metrics across all scenarios."""
    if not results:
        return {}

    n = len(results)
    return {
        "system": results[0].system_name,
        "scenarios": n,
        "top_pick_accuracy": sum(r.top_pick_quality for r in results) / n,
        "avg_top3_recall": sum(r.top_3_recall for r in results) / n,
        "bad_pick_avoidance": sum(r.bad_pick_avoidance for r in results) / n,
        "avg_latency_ms": sum(r.latency_ms for r in results) / n,
        "avg_tool_calls": sum(r.tool_call_count for r in results) / n,
        # break down by difficulty
        "by_difficulty": _by_difficulty(results),
    }


def _by_difficulty(results: list[EvalResult]) -> dict:
    """Group metrics by scenario difficulty — this is where multi-agent should shine."""
    from collections import defaultdict

    groups: dict[str, list[EvalResult]] = defaultdict(list)

    # we need the scenario difficulty, which isn't in EvalResult
    # so we'll just return per-scenario for now and the comparison
    # runner will handle grouping with the scenarios
    return {}
