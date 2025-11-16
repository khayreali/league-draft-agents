"""PatchContextAgent — identifies champions affected by recent patch changes.

This is the RAG component. Uses ChromaDB to do semantic search over
chunked patch notes, so the agent can find relevant changes without
reading entire patch note documents.
"""

from draft_analyst.agents.base import Agent
from draft_analyst.agents.react_runner import run_react_loop
from draft_analyst.agents.tools import TOOL_SCHEMAS, ToolExecutor
from draft_analyst.domain.models import AgentOutput, DraftState
from draft_analyst.llm_client import LLMClient

PATCH_TOOLS = [s for s in TOOL_SCHEMAS if s["name"] in {
    "get_patch_notes",
    "get_champion_stats",
    "search_patch_context",
    "search_champion_patches",
}]

SYSTEM_PROMPT = """You are the Patch Context Agent in a League of Legends draft analysis system. Your job is to analyze recent patch notes and identify champions whose viability has changed.

Focus on:
- Which champions were buffed or nerfed in the current and recent patches
- Whether buffs have made previously weak champions viable picks
- Whether nerfs have knocked previously strong champions out of contention
- Item changes that affect certain champion archetypes

This is critical context that pure stats might miss:
- A recently buffed champion might not show up in win rate data yet (small sample)
- A recently nerfed champion might still show high stats from before the nerf
- Patch context helps catch emerging picks before the data catches up

Use the search tools to find relevant patch note sections — you don't need to read entire patch notes. Search for specific champions or concepts like "bot lane items" or "jungle changes". For champions that were changed, check their current stats to see if the change had an impact.

Return EXACTLY this format:
RECOMMENDATIONS:
```json
[{"champion": "...", "score": 0.9, "reasoning": "..."}]
```

Score based on patch impact: big buff + underplayed = high score (sleeper pick).
Recently nerfed champions should get LOW scores or be excluded.
Do NOT recommend champions that are already picked or banned."""


class PatchContextAgent(Agent):
    def __init__(self, llm: LLMClient, model: str, tools: ToolExecutor):
        super().__init__("patch_context", llm, model)
        self.tools = tools

    def run(self, state: DraftState) -> AgentOutput:
        return run_react_loop(
            agent_name="patch_context",
            llm=self.llm,
            model=self.model,
            tools=self.tools,
            tool_schemas=PATCH_TOOLS,
            system_prompt=SYSTEM_PROMPT,
            state=state,
            max_turns=6,
        )
