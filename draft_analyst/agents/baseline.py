"""Single-agent baseline for the eval comparison.

One ReAct-style loop with all tools available. This is what the
multi-agent system has to beat — if it can't, the orchestration
isn't worth the complexity.
"""
from draft_analyst.agents.base import Agent
from draft_analyst.agents.react_runner import run_react_loop
from draft_analyst.agents.tools import TOOL_SCHEMAS, ToolExecutor
from draft_analyst.domain.models import AgentOutput, DraftState
from draft_analyst.llm_client import LLMClient

SYSTEM_PROMPT = """You are a League of Legends draft analyst. Given a partial draft state, recommend the best champion picks for the user's role.

You have access to tools that query:
- Solo queue statistics (win rates, pick rates, matchup deltas)
- Pro play data (what's being picked at the highest level and why)
- Synergy data (which champions perform well together)
- Counter-pick data (which champions have favorable matchups against the enemy team)
- Patch notes (recent champion changes that affect viability)

Your job:
1. Use the tools to gather data about the current draft situation
2. Consider which champions are strong in the current meta (solo queue + pro)
3. Check which champions counter the enemy team composition
4. Evaluate how candidates synergize with the user's existing teammates
5. Check if recent patch changes affect any of your candidates

Return your final answer as a JSON array of recommendations, ordered from best to worst. Each recommendation should have:
- "champion": the champion name
- "score": a confidence score from 0-1
- "reasoning": 1-2 sentences explaining why, citing specific data

Return EXACTLY this format at the end of your analysis:
RECOMMENDATIONS:
```json
[{"champion": "...", "score": 0.9, "reasoning": "..."}]
```

Be thorough but efficient — don't call the same tool twice with the same arguments.
Do NOT recommend champions that are already picked or banned."""


class SingleAgentBaseline(Agent):
    def __init__(self, llm: LLMClient, model: str, tools: ToolExecutor):
        super().__init__("baseline", llm, model)
        self.tools = tools

    def run(self, state: DraftState) -> AgentOutput:
        return run_react_loop(
            agent_name="baseline",
            llm=self.llm,
            model=self.model,
            tools=self.tools,
            tool_schemas=TOOL_SCHEMAS,
            system_prompt=SYSTEM_PROMPT,
            state=state,
            max_turns=15,
        )
