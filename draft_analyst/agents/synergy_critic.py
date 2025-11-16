"""SynergyCriticAgent — evaluates whether a candidate pick fits the team comp.

Acts as a critic: given a candidate from one of the other agents plus the
current team, checks if the pick actually works with the existing comp.
"""
import json
import logging

from draft_analyst.agents.tools import TOOL_SCHEMAS, ToolExecutor
from draft_analyst.domain.models import DraftState, Recommendation
from draft_analyst.llm_client import LLMClient
from draft_analyst.config import DEFAULT_CHEAP_MODEL

log = logging.getLogger(__name__)

SYNERGY_TOOLS = [s for s in TOOL_SCHEMAS if s["name"] in {
    "get_synergy",
    "get_team_synergy",
    "get_candidate_synergy",
}]

SYSTEM_PROMPT = """You are the Synergy Critic in a League of Legends draft analysis system. Your job is to evaluate whether a candidate champion pick fits with the user's existing team composition.

You will be given a candidate champion and the current team picks. Use the synergy tools to check:
- How well the candidate synergizes with each existing teammate
- The overall team synergy if this candidate is added
- Whether the candidate fills a gap in the composition (e.g., missing engage, missing AP damage)

Return a JSON object with your evaluation:
```json
{"champion": "...", "synergy_score": 0.7, "verdict": "good fit / neutral / poor fit", "reasoning": "..."}
```

Be honest — if the pick doesn't fit the comp, say so. A statistically strong champion that clashes with the team comp is worse than a slightly weaker champion that completes it."""


class SynergyCriticAgent:
    """Not a full Agent — it's a critic that evaluates individual candidates.

    The HeadCoach calls this on top candidates before making final recs.
    Uses the cheaper model since it's doing simpler evaluation.
    """

    def __init__(self, llm: LLMClient, tools: ToolExecutor, model: str | None = None):
        self.llm = llm
        self.tools = tools
        self.model = model or DEFAULT_CHEAP_MODEL

    def evaluate(self, candidate: Recommendation, state: DraftState) -> dict:
        """Evaluate a single candidate pick against the team comp."""
        if not state.user_team_picks:
            # nothing to evaluate synergy against
            return {
                "champion": candidate.champion,
                "synergy_score": 0.5,
                "verdict": "neutral",
                "reasoning": "no existing teammates to evaluate synergy with",
            }

        user_msg = (
            f"Evaluate {candidate.champion} as a pick for {state.user_role}.\n"
            f"Current team: {', '.join(state.user_team_picks)}\n"
            f"Enemy team: {', '.join(state.enemy_team_picks)}\n"
            f"This champion was recommended because: {candidate.reasoning}"
        )

        messages = [{"role": "user", "content": user_msg}]

        # give it a couple turns to call tools + respond
        for _ in range(4):
            response = self.llm.chat(
                messages=messages,
                model=self.model,
                tools=SYNERGY_TOOLS,
                system=SYSTEM_PROMPT,
            )

            content_blocks = response["content"]
            stop_reason = response["stop_reason"]

            text_parts = []
            tool_uses = []
            for block in content_blocks:
                if hasattr(block, "type"):
                    if block.type == "text":
                        text_parts.append(block.text)
                    elif block.type == "tool_use":
                        tool_uses.append(block)
                elif isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        tool_uses.append(block)

            if not tool_uses or stop_reason == "end_turn":
                return self._parse_verdict(
                    "\n".join(text_parts), candidate.champion
                )

            messages.append({"role": "assistant", "content": content_blocks})

            tool_results = []
            for tu in tool_uses:
                tid = tu.id if hasattr(tu, "id") else tu.get("id")
                name = tu.name if hasattr(tu, "name") else tu.get("name")
                inp = tu.input if hasattr(tu, "input") else tu.get("input", {})
                result_str = self.tools.execute(name, inp)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": result_str,
                })

            messages.append({"role": "user", "content": tool_results})

        return {
            "champion": candidate.champion,
            "synergy_score": 0.5,
            "verdict": "neutral",
            "reasoning": "critic timed out",
        }

    def _parse_verdict(self, text: str, champion: str) -> dict:
        try:
            if "```json" in text:
                start = text.index("```json") + 7
                end = text.index("```", start)
                parsed = json.loads(text[start:end].strip())
            elif "{" in text:
                brace_start = text.index("{")
                brace_end = text.rindex("}") + 1
                parsed = json.loads(text[brace_start:brace_end])
            else:
                parsed = None

            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list) and parsed:
                return parsed[0] if isinstance(parsed[0], dict) else {}
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "champion": champion,
            "synergy_score": 0.5,
            "verdict": "neutral",
            "reasoning": text[:200] if text else "no verdict produced",
        }
