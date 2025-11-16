"""StatsAgent — focuses on solo queue win rates and counter-pick matchups."""

from draft_analyst.agents.base import Agent
from draft_analyst.agents.react_runner import run_react_loop
from draft_analyst.agents.tools import TOOL_SCHEMAS, ToolExecutor
from draft_analyst.domain.models import AgentOutput, DraftState
from draft_analyst.llm_client import LLMClient

# only gets the solo queue / matchup tools
STATS_TOOLS = [s for s in TOOL_SCHEMAS if s["name"] in {
    "get_champion_stats",
    "get_top_champions",
    "get_matchup_delta",
    "get_counter_picks",
}]

SYSTEM_PROMPT = """You are the Stats Agent in a League of Legends draft analysis system. Your job is to analyze solo queue statistics and matchup data to identify strong picks.

Focus on:
- Which champions have the highest win rates right now (use Wilson lower bound to avoid small-sample flukes)
- Which champions counter the enemy team's picks (positive matchup deltas)
- Whether a candidate has enough games to be statistically reliable

You should:
1. Check the top champions by win rate
2. If there are enemy picks, find counter-picks with favorable matchup deltas
3. For promising candidates, pull their individual stats to verify

Your output should be a ranked list of candidates from a PURE STATS perspective. Don't worry about team synergy or pro meta — other agents handle those.

Return EXACTLY this format:
RECOMMENDATIONS:
```json
[{"champion": "...", "score": 0.9, "reasoning": "..."}]
```

Score based on statistical strength: high WR + positive matchup deltas = high score.
Do NOT recommend champions that are already picked or banned."""


class StatsAgent(Agent):
    def __init__(self, llm: LLMClient, model: str, tools: ToolExecutor):
        super().__init__("stats", llm, model)
        self.tools = tools

    def run(self, state: DraftState) -> AgentOutput:
        return run_react_loop(
            agent_name="stats",
            llm=self.llm,
            model=self.model,
            tools=self.tools,
            tool_schemas=STATS_TOOLS,
            system_prompt=SYSTEM_PROMPT,
            state=state,
            max_turns=8,
        )
