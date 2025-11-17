"""LangGraph coordinator — wires the multi-agent system together.

The graph runs StatsAgent, ProMetaAgent, and PatchContextAgent in parallel,
then routes their outputs to HeadCoachAgent for synthesis.
"""
import logging
import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END

from draft_analyst.agents.head_coach import HeadCoachAgent
from draft_analyst.agents.patch_agent import PatchContextAgent
from draft_analyst.agents.pro_meta_agent import ProMetaAgent
from draft_analyst.agents.stats_agent import StatsAgent
from draft_analyst.agents.tools import ToolExecutor
from draft_analyst.domain.models import AgentOutput, DraftState
from draft_analyst.llm_client import LLMClient

log = logging.getLogger(__name__)


class CoordinatorState(TypedDict):
    draft_state: DraftState
    agent_outputs: Annotated[list[AgentOutput], operator.add]
    final_output: AgentOutput | None


class LangGraphCoordinator:
    """Multi-agent draft recommender using LangGraph for orchestration."""

    def __init__(self, llm: LLMClient, model: str, tools: ToolExecutor):
        self.llm = llm
        self.model = model
        self.tools = tools

        self.stats_agent = StatsAgent(llm, model, tools)
        self.pro_meta_agent = ProMetaAgent(llm, model, tools)
        self.patch_agent = PatchContextAgent(llm, model, tools)
        self.head_coach = HeadCoachAgent(llm, model, tools)

        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(CoordinatorState)

        builder.add_node("stats", self._run_stats)
        builder.add_node("pro_meta", self._run_pro_meta)
        builder.add_node("patch_context", self._run_patch_context)
        builder.add_node("head_coach", self._run_head_coach)

        # fan out from START to all three specialists
        builder.add_edge(START, "stats")
        builder.add_edge(START, "pro_meta")
        builder.add_edge(START, "patch_context")

        # fan in: all specialists feed into head_coach
        builder.add_edge("stats", "head_coach")
        builder.add_edge("pro_meta", "head_coach")
        builder.add_edge("patch_context", "head_coach")

        builder.add_edge("head_coach", END)

        return builder.compile()

    def _run_stats(self, state: CoordinatorState) -> dict:
        log.info("running stats agent...")
        output = self.stats_agent.run(state["draft_state"])
        log.info(f"stats agent: {len(output.recommendations)} recs")
        return {"agent_outputs": [output]}

    def _run_pro_meta(self, state: CoordinatorState) -> dict:
        log.info("running pro meta agent...")
        output = self.pro_meta_agent.run(state["draft_state"])
        log.info(f"pro meta agent: {len(output.recommendations)} recs")
        return {"agent_outputs": [output]}

    def _run_patch_context(self, state: CoordinatorState) -> dict:
        log.info("running patch context agent...")
        output = self.patch_agent.run(state["draft_state"])
        log.info(f"patch context agent: {len(output.recommendations)} recs")
        return {"agent_outputs": [output]}

    def _run_head_coach(self, state: CoordinatorState) -> dict:
        log.info(f"running head coach with {len(state['agent_outputs'])} specialist outputs...")
        output = self.head_coach.synthesize(
            state["draft_state"],
            state["agent_outputs"],
        )
        log.info(f"head coach: {len(output.recommendations)} final recs")
        return {"final_output": output}

    def run(self, state: DraftState) -> AgentOutput:
        start = time.time()

        result = self.graph.invoke({
            "draft_state": state,
            "agent_outputs": [],
            "final_output": None,
        })

        elapsed = (time.time() - start) * 1000
        output = result["final_output"]

        if output is None:
            log.error("coordinator produced no output")
            return AgentOutput(
                agent_name="multi_agent",
                recommendations=[],
                raw_reasoning="coordinator failed to produce output",
                tool_calls_made=0,
            )

        # rebrand for the eval
        output.agent_name = "multi_agent"
        log.info(f"multi-agent system finished in {elapsed:.0f}ms")
        return output
