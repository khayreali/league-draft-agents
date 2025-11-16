"""HeadCoachAgent — synthesizes specialist outputs into final recommendations.

Gets the outputs from StatsAgent, ProMetaAgent, PatchContextAgent,
runs SynergyCritic on top candidates, then produces a final ranked
list with reasoning that cites which agent contributed which insight.
"""
import json
import logging
from collections import defaultdict

from draft_analyst.agents.synergy_critic import SynergyCriticAgent
from draft_analyst.agents.tools import ToolExecutor
from draft_analyst.domain.models import AgentOutput, DraftState, Recommendation
from draft_analyst.llm_client import LLMClient

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Head Coach in a League of Legends draft analysis system. You synthesize recommendations from three specialist analysts and a synergy critic to produce the final pick recommendation.

You will receive:
1. Recommendations from the Stats Agent (solo queue win rates and matchup data)
2. Recommendations from the Pro Meta Agent (professional play trends)
3. Recommendations from the Patch Context Agent (recent buff/nerf analysis)
4. Synergy evaluations for the top candidates (how well they fit the team comp)

Your job is to weigh these perspectives and produce a final ranked recommendation. Consider:
- A champion recommended by multiple agents is likely a strong pick
- Synergy with the existing team comp matters — a great stat champion that doesn't fit is worse than a good one that does
- Patch context can override stats: recently nerfed champions should be downranked even if stats are still high, recently buffed champions might be sleepers
- Pro meta trends signal organized-play viability, which is useful context

In your reasoning, CITE which agent's data supports each recommendation. For example: "Aurora (stats: 54% WR, pro: trending pick in LCK, patch: buffed in 16.7, synergy: good fit with Sejuani)."

Return EXACTLY this format:
RECOMMENDATIONS:
```json
[{"champion": "...", "score": 0.9, "reasoning": "..."}]
```

Return your top 5 picks. Do NOT recommend champions that are already picked or banned."""


class HeadCoachAgent:
    def __init__(self, llm: LLMClient, model: str, tools: ToolExecutor):
        self.llm = llm
        self.model = model
        self.tools = tools
        self.critic = SynergyCriticAgent(llm, tools)

    def synthesize(
        self,
        state: DraftState,
        agent_outputs: list[AgentOutput],
    ) -> AgentOutput:
        # collect top unique candidates across all agents
        candidates = self._merge_candidates(agent_outputs, state)
        top_candidates = candidates[:8]  # evaluate top 8

        # run synergy critic on each
        synergy_verdicts = {}
        for rec in top_candidates:
            verdict = self.critic.evaluate(rec, state)
            synergy_verdicts[rec.champion] = verdict
            log.info(f"synergy critic: {rec.champion} -> {verdict.get('verdict', '?')}")

        # build context message for the synthesis LLM call
        context = self._build_context(state, agent_outputs, top_candidates, synergy_verdicts)

        response = self.llm.chat(
            messages=[{"role": "user", "content": context}],
            model=self.model,
            system=SYSTEM_PROMPT,
        )

        text = self._extract_text(response)
        recs = self._parse_recs(text, state)

        total_tool_calls = sum(o.tool_calls_made for o in agent_outputs)

        return AgentOutput(
            agent_name="head_coach",
            recommendations=recs,
            raw_reasoning=text,
            tool_calls_made=total_tool_calls,
        )

    def _merge_candidates(
        self, outputs: list[AgentOutput], state: DraftState,
    ) -> list[Recommendation]:
        """Deduplicate and rank candidates across all agent outputs."""
        unavailable = set(state.bans + state.user_team_picks + state.enemy_team_picks)
        scores: dict[str, list[float]] = defaultdict(list)
        reasons: dict[str, list[str]] = defaultdict(list)
        sources: dict[str, list[str]] = defaultdict(list)

        for output in outputs:
            for rec in output.recommendations:
                if rec.champion in unavailable:
                    continue
                scores[rec.champion].append(rec.score)
                reasons[rec.champion].append(f"[{output.agent_name}] {rec.reasoning}")
                sources[rec.champion].append(output.agent_name)

        merged = []
        for champ, score_list in scores.items():
            # champions recommended by more agents get a boost
            avg_score = sum(score_list) / len(score_list)
            multi_agent_boost = min(0.1 * (len(score_list) - 1), 0.2)
            merged.append(Recommendation(
                champion=champ,
                score=min(avg_score + multi_agent_boost, 1.0),
                reasoning=" | ".join(reasons[champ]),
                sources=list(set(sources[champ])),
            ))

        merged.sort(key=lambda r: r.score, reverse=True)
        return merged

    def _build_context(
        self,
        state: DraftState,
        outputs: list[AgentOutput],
        candidates: list[Recommendation],
        verdicts: dict[str, dict],
    ) -> str:
        parts = [
            f"Draft state: patch {state.patch}, role: {state.user_role}",
            f"Team: {', '.join(state.user_team_picks) or 'none yet'}",
            f"Enemy: {', '.join(state.enemy_team_picks) or 'none yet'}",
            f"Bans: {', '.join(state.bans) or 'none'}",
            "",
            "--- SPECIALIST RECOMMENDATIONS ---",
        ]

        for output in outputs:
            parts.append(f"\n{output.agent_name.upper()} AGENT:")
            if output.recommendations:
                for r in output.recommendations[:5]:
                    parts.append(f"  {r.champion} (score: {r.score:.2f}): {r.reasoning}")
            else:
                parts.append("  (no recommendations)")

        parts.append("\n--- SYNERGY EVALUATIONS ---")
        for champ, verdict in verdicts.items():
            v = verdict.get("verdict", "unknown")
            score = verdict.get("synergy_score", 0.5)
            reason = verdict.get("reasoning", "")
            parts.append(f"  {champ}: {v} (synergy: {score:.2f}) — {reason}")

        parts.append("\n--- MERGED CANDIDATE RANKING ---")
        for i, rec in enumerate(candidates[:8], 1):
            agents = ", ".join(rec.sources)
            parts.append(f"  {i}. {rec.champion} (avg score: {rec.score:.2f}, from: {agents})")

        parts.append("\nBased on all the above, give me your final top 5 recommendations.")
        return "\n".join(parts)

    def _extract_text(self, response: dict) -> str:
        parts = []
        for block in response["content"]:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)

    def _parse_recs(self, text: str, state: DraftState) -> list[Recommendation]:
        recs = []
        try:
            if "```json" in text:
                start = text.index("```json") + 7
                end = text.index("```", start)
                raw = text[start:end].strip()
            elif "RECOMMENDATIONS:" in text:
                after = text.split("RECOMMENDATIONS:")[-1]
                bracket_start = after.index("[")
                bracket_end = after.rindex("]") + 1
                raw = after[bracket_start:bracket_end]
            else:
                bracket_start = text.rindex("[")
                bracket_end = text.rindex("]") + 1
                raw = text[bracket_start:bracket_end]

            parsed = json.loads(raw)
            unavailable = set(state.bans + state.user_team_picks + state.enemy_team_picks)
            for item in parsed:
                champ = item.get("champion", "")
                if champ in unavailable:
                    continue
                recs.append(Recommendation(
                    champion=champ,
                    score=float(item.get("score", 0.5)),
                    reasoning=item.get("reasoning", ""),
                    sources=["head_coach"],
                ))
        except (json.JSONDecodeError, ValueError) as e:
            log.warning(f"head coach failed to parse recs: {e}")

        return recs
