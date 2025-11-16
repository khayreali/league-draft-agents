"""ProMetaAgent — focuses on what's being picked and winning in pro play."""

from draft_analyst.agents.base import Agent
from draft_analyst.agents.react_runner import run_react_loop
from draft_analyst.agents.tools import TOOL_SCHEMAS, ToolExecutor
from draft_analyst.domain.models import AgentOutput, DraftState
from draft_analyst.llm_client import LLMClient

PRO_TOOLS = [s for s in TOOL_SCHEMAS if s["name"] in {
    "get_pro_presence",
    "get_pro_top_picks",
    "get_pro_trending",
}]

SYSTEM_PROMPT = """You are the Pro Meta Agent in a League of Legends draft analysis system. Your job is to analyze professional play trends to identify champions that are being prioritized at the highest level.

Focus on:
- Which champions pro teams are picking most and why
- Which champions are trending (high pick rate + winning record)
- What compositions those champions tend to appear in (common teammates)

Pro trends matter because:
- Pro players optimize picks for coordinated play
- If a champion is suddenly seeing more pro play, there's usually a reason
- Team compositions that work in pro often indicate strong synergies

Your output should rank candidates from a PRO META perspective. Don't worry about solo queue stats or individual matchups — other agents handle those.

Return EXACTLY this format:
RECOMMENDATIONS:
```json
[{"champion": "...", "score": 0.9, "reasoning": "..."}]
```

Score based on pro relevance: high pick rate + high win rate in pro = high score.
A champion trending upward in pro is worth flagging even if sample size is small.
Do NOT recommend champions that are already picked or banned."""


class ProMetaAgent(Agent):
    def __init__(self, llm: LLMClient, model: str, tools: ToolExecutor):
        super().__init__("pro_meta", llm, model)
        self.tools = tools

    def run(self, state: DraftState) -> AgentOutput:
        return run_react_loop(
            agent_name="pro_meta",
            llm=self.llm,
            model=self.model,
            tools=self.tools,
            tool_schemas=PRO_TOOLS,
            system_prompt=SYSTEM_PROMPT,
            state=state,
            max_turns=6,
        )
