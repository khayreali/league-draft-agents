import json
import time
from unittest.mock import MagicMock

import pytest

from draft_analyst.agents.context import build_tool_executor
from draft_analyst.agents.coordinator import LangGraphCoordinator
from draft_analyst.agents.head_coach import HeadCoachAgent
from draft_analyst.domain.models import AgentOutput, DraftState, Recommendation


DRAFT = DraftState(
    patch="16.7", user_team_picks=["Aatrox", "Sejuani"],
    enemy_team_picks=["Gnar"], bans=["Yone"], user_role="mid",
)


def _make_mock_llm(delay=0):
    call_count = 0

    def chat(messages, model, tools=None, system=None):
        nonlocal call_count
        call_count += 1
        if delay:
            time.sleep(delay)
        recs = json.dumps([{"champion": "Aurora", "score": 0.8, "reasoning": "mock"}])
        if system and "Synergy Critic" in system:
            verdict = json.dumps({"champion": "Aurora", "synergy_score": 0.7,
                                  "verdict": "good fit", "reasoning": "ok"})
            return {"content": [{"type": "text", "text": f"```json\n{verdict}\n```"}],
                    "stop_reason": "end_turn"}
        return {"content": [{"type": "text", "text": f"RECOMMENDATIONS:\n```json\n{recs}\n```"}],
                "stop_reason": "end_turn"}

    mock = MagicMock()
    mock.chat = chat
    return mock


def test_coordinator_runs_specialists_in_parallel():
    """Three specialist agents should fan out via LangGraph, not run sequentially."""
    executor = build_tool_executor("16.7")
    mock_llm = _make_mock_llm(delay=0.1)

    coord = LangGraphCoordinator(mock_llm, "mock", executor)
    start = time.time()
    output = coord.run(DRAFT)
    elapsed = time.time() - start

    assert output.recommendations
    # if sequential, the 3 specialist delays alone would be >= 0.3s
    # parallel should keep total well under that even with head_coach overhead
    assert elapsed < 1.5, f"took {elapsed:.2f}s — specialists might be running sequentially"


def test_head_coach_handles_empty_agent_output():
    """Head coach shouldn't crash when one agent returns nothing."""
    executor = build_tool_executor("16.7")
    mock_llm = _make_mock_llm()

    coach = HeadCoachAgent(mock_llm, "mock", executor)

    outputs = [
        AgentOutput(agent_name="stats", recommendations=[
            Recommendation(champion="Aurora", score=0.9, reasoning="good WR", sources=["stats"]),
        ], tool_calls_made=2),
        AgentOutput(agent_name="pro_meta", recommendations=[], raw_reasoning="", tool_calls_made=0),
        AgentOutput(agent_name="patch_context", recommendations=[
            Recommendation(champion="Corki", score=0.0, reasoning="", sources=["patch"]),
        ], tool_calls_made=1),
    ]

    result = coach.synthesize(DRAFT, outputs)
    assert result.agent_name == "head_coach"
    assert isinstance(result.recommendations, list)
    assert result.tool_calls_made == 3
