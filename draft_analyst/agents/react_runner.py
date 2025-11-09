"""Shared ReAct loop used by all agents.

Extracted from the baseline so i don't copy-paste the same tool
execution loop into every agent file.
"""
import json
import logging
import time

from draft_analyst.agents.tools import ToolExecutor
from draft_analyst.domain.models import AgentOutput, DraftState, Recommendation
from draft_analyst.llm_client import LLMClient

log = logging.getLogger(__name__)


def build_user_message(state: DraftState) -> str:
    parts = [f"Patch: {state.patch}", f"My role: {state.user_role}"]
    if state.user_team_picks:
        parts.append(f"My team's picks so far: {', '.join(state.user_team_picks)}")
    if state.enemy_team_picks:
        parts.append(f"Enemy team's picks: {', '.join(state.enemy_team_picks)}")
    if state.bans:
        parts.append(f"Bans: {', '.join(state.bans)}")
    parts.append(f"Rank context: {state.rank}")
    return "\n".join(parts)


def run_react_loop(
    agent_name: str,
    llm: LLMClient,
    model: str,
    tools: ToolExecutor,
    tool_schemas: list[dict],
    system_prompt: str,
    state: DraftState,
    max_turns: int = 10,
) -> AgentOutput:
    """Run a ReAct loop: LLM calls tools, we execute, repeat until done."""
    start = time.time()
    tool_call_count = 0
    user_msg = build_user_message(state)

    messages = [{"role": "user", "content": user_msg}]

    for turn in range(max_turns):
        response = llm.chat(
            messages=messages,
            model=model,
            tools=tool_schemas,
            system=system_prompt,
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

        full_text = "\n".join(text_parts)

        if not tool_uses or stop_reason == "end_turn":
            recs = parse_recommendations(full_text, state, agent_name)
            elapsed = (time.time() - start) * 1000
            log.info(f"{agent_name} finished in {elapsed:.0f}ms, {tool_call_count} tool calls")
            return AgentOutput(
                agent_name=agent_name,
                recommendations=recs,
                raw_reasoning=full_text,
                tool_calls_made=tool_call_count,
            )

        messages.append({"role": "assistant", "content": content_blocks})

        tool_results = []
        for tool_use in tool_uses:
            tid = tool_use.id if hasattr(tool_use, "id") else tool_use.get("id")
            name = tool_use.name if hasattr(tool_use, "name") else tool_use.get("name")
            inp = tool_use.input if hasattr(tool_use, "input") else tool_use.get("input", {})

            result_str = tools.execute(name, inp)
            tool_call_count += 1
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tid,
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results})

    log.warning(f"{agent_name} hit max turns ({max_turns})")
    return AgentOutput(
        agent_name=agent_name,
        recommendations=[],
        raw_reasoning="hit max turns",
        tool_calls_made=tool_call_count,
    )


def parse_recommendations(text: str, state: DraftState, source: str) -> list[Recommendation]:
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
                sources=[source],
            ))
    except (json.JSONDecodeError, ValueError) as e:
        log.warning(f"failed to parse recs from {source}: {e}")

    return recs
