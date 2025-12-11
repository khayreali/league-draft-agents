"""ComparisonRunner — the main eval entry point.

Runs both systems on the same scenarios, prints a side-by-side table,
and writes results to JSON. This is the most important class in the
project — it's how you show the multi-agent orchestration was worth it.
"""
import json
import logging
from collections import defaultdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

from draft_analyst.agents.baseline import SingleAgentBaseline
from draft_analyst.agents.coordinator import LangGraphCoordinator
from draft_analyst.agents.context import build_tool_executor
from draft_analyst.config import DEFAULT_AGENT_MODEL
from draft_analyst.domain.models import EvalResult, EvalScenario
from draft_analyst.evaluation.evaluator import Evaluator, aggregate_results
from draft_analyst.llm_client import get_llm_client

log = logging.getLogger(__name__)


class ComparisonRunner:
    def __init__(self, scenarios: list[EvalScenario], output_path: str = "eval/results.json"):
        self.scenarios = scenarios
        self.output_path = output_path
        self.console = Console()

    def run(self) -> dict:
        """Run both systems, compare, print results, save to JSON."""
        tool_executor = build_tool_executor()
        llm = get_llm_client()

        baseline = SingleAgentBaseline(llm, DEFAULT_AGENT_MODEL, tool_executor)
        multi_agent = LangGraphCoordinator(llm, DEFAULT_AGENT_MODEL, tool_executor)

        self.console.print("\n[bold]Running single-agent baseline...[/bold]")
        baseline_eval = Evaluator(baseline.run)
        baseline_results = baseline_eval.evaluate(self.scenarios)

        self.console.print("\n[bold]Running multi-agent system...[/bold]")
        multi_eval = Evaluator(multi_agent.run)
        multi_results = multi_eval.evaluate(self.scenarios)

        # print comparison
        self._print_per_scenario(baseline_results, multi_results)
        self._print_summary(baseline_results, multi_results)
        self._print_by_difficulty(baseline_results, multi_results)

        # save to JSON
        output = {
            "baseline": self._results_to_dict(baseline_results),
            "multi_agent": self._results_to_dict(multi_results),
            "baseline_summary": aggregate_results(baseline_results),
            "multi_agent_summary": aggregate_results(multi_results),
        }
        Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        self.console.print(f"\nresults saved to {self.output_path}")

        return output

    def _print_per_scenario(self, baseline: list[EvalResult], multi: list[EvalResult]):
        table = Table(title="Per-Scenario Results")
        table.add_column("Scenario", style="bold")
        table.add_column("Diff", style="dim")
        table.add_column("B: Top Pick", justify="center")
        table.add_column("M: Top Pick", justify="center")
        table.add_column("B: Top3 Recall", justify="right")
        table.add_column("M: Top3 Recall", justify="right")
        table.add_column("B: Bad Avoid", justify="center")
        table.add_column("M: Bad Avoid", justify="center")

        for b, m, s in zip(baseline, multi, self.scenarios):
            b_top = "[green]Y[/green]" if b.top_pick_quality else "[red]N[/red]"
            m_top = "[green]Y[/green]" if m.top_pick_quality else "[red]N[/red]"
            b_bad = "[green]Y[/green]" if b.bad_pick_avoidance else "[red]N[/red]"
            m_bad = "[green]Y[/green]" if m.bad_pick_avoidance else "[red]N[/red]"

            table.add_row(
                s.name, s.difficulty,
                b_top, m_top,
                f"{b.top_3_recall:.2f}", f"{m.top_3_recall:.2f}",
                b_bad, m_bad,
            )

        self.console.print(table)

    def _print_summary(self, baseline: list[EvalResult], multi: list[EvalResult]):
        b_agg = aggregate_results(baseline)
        m_agg = aggregate_results(multi)

        table = Table(title="Overall Comparison")
        table.add_column("Metric")
        table.add_column("Baseline", justify="right")
        table.add_column("Multi-Agent", justify="right")
        table.add_column("Delta", justify="right")

        metrics = [
            ("Top Pick Accuracy", "top_pick_accuracy", "{:.1%}"),
            ("Avg Top-3 Recall", "avg_top3_recall", "{:.1%}"),
            ("Bad Pick Avoidance", "bad_pick_avoidance", "{:.1%}"),
            ("Avg Latency (ms)", "avg_latency_ms", "{:.0f}"),
            ("Avg Tool Calls", "avg_tool_calls", "{:.1f}"),
        ]

        for label, key, fmt in metrics:
            bv = b_agg.get(key, 0)
            mv = m_agg.get(key, 0)
            delta = mv - bv

            # for latency, lower is better
            if key in ("avg_latency_ms", "avg_tool_calls"):
                delta_str = fmt.format(delta)
            else:
                sign = "+" if delta > 0 else ""
                delta_str = sign + fmt.format(delta)

            table.add_row(label, fmt.format(bv), fmt.format(mv), delta_str)

        self.console.print(table)

    def _print_by_difficulty(self, baseline: list[EvalResult], multi: list[EvalResult]):
        """The money table — multi-agent should win on hard scenarios."""
        groups: dict[str, dict[str, list[EvalResult]]] = defaultdict(lambda: {"baseline": [], "multi_agent": []})

        for b, m, s in zip(baseline, multi, self.scenarios):
            groups[s.difficulty]["baseline"].append(b)
            groups[s.difficulty]["multi_agent"].append(m)

        table = Table(title="By Difficulty (where multi-agent should shine)")
        table.add_column("Difficulty", style="bold")
        table.add_column("B: Top Pick %", justify="right")
        table.add_column("M: Top Pick %", justify="right")
        table.add_column("B: Avg Recall", justify="right")
        table.add_column("M: Avg Recall", justify="right")

        for diff in ["easy", "medium", "hard"]:
            if diff not in groups:
                continue
            b_list = groups[diff]["baseline"]
            m_list = groups[diff]["multi_agent"]
            n = len(b_list)
            if n == 0:
                continue

            b_top = sum(r.top_pick_quality for r in b_list) / n
            m_top = sum(r.top_pick_quality for r in m_list) / n
            b_rec = sum(r.top_3_recall for r in b_list) / n
            m_rec = sum(r.top_3_recall for r in m_list) / n

            table.add_row(
                f"{diff} (n={n})",
                f"{b_top:.0%}", f"{m_top:.0%}",
                f"{b_rec:.2f}", f"{m_rec:.2f}",
            )

        self.console.print(table)

    def _results_to_dict(self, results: list[EvalResult]) -> list[dict]:
        out = []
        for r in results:
            d = r.model_dump()
            d["recommendations"] = [
                {"champion": rec.champion, "score": rec.score, "reasoning": rec.reasoning}
                for rec in r.recommendations[:5]
            ]
            out.append(d)
        return out
