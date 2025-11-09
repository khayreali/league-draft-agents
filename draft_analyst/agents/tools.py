"""Tool definitions for the draft agents.

Each tool wraps an analytics method. The TOOL_SCHEMAS list is what gets
passed to the LLM, and execute_tool() dispatches calls by name.
"""
import json
import logging

from draft_analyst.analytics.champion_stats import ChampionStats
from draft_analyst.analytics.counter_pick import CounterPickAnalyzer
from draft_analyst.analytics.pro_meta import ProMetaAnalyzer
from draft_analyst.analytics.synergy import SynergyCalculator
from draft_analyst.data.patch_index import PatchIndex

log = logging.getLogger(__name__)

TOOL_SCHEMAS = [
    {
        "name": "get_champion_stats",
        "description": "Get win rate, pick rate, and confidence intervals for a champion in solo queue. Returns None if no data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "champion": {"type": "string", "description": "Champion name, e.g. 'Ahri'"},
            },
            "required": ["champion"],
        },
    },
    {
        "name": "get_top_champions",
        "description": "Get the top champions by win rate (ranked by Wilson lower bound to handle small samples). Useful for identifying the strongest overall picks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_games": {"type": "integer", "description": "Minimum games to qualify", "default": 5},
                "limit": {"type": "integer", "description": "How many to return", "default": 15},
            },
            "required": [],
        },
    },
    {
        "name": "get_matchup_delta",
        "description": "Get how a champion performs against a specific opponent compared to their baseline win rate. Positive delta means they do better than usual against this opponent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "champion": {"type": "string"},
                "opponent": {"type": "string"},
            },
            "required": ["champion", "opponent"],
        },
    },
    {
        "name": "get_counter_picks",
        "description": "Find champions with favorable matchup deltas against the given enemy team. Returns ranked list of counter-picks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "enemy_picks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of enemy champion names",
                },
                "role": {"type": "string", "description": "Filter to this role (optional)"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["enemy_picks"],
        },
    },
    {
        "name": "get_pro_presence",
        "description": "Get a champion's pick rate, win rate, and most common teammates in pro play.",
        "input_schema": {
            "type": "object",
            "properties": {
                "champion": {"type": "string"},
            },
            "required": ["champion"],
        },
    },
    {
        "name": "get_pro_top_picks",
        "description": "Get the most picked champions in pro play, with win rates and common teammates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 15},
            },
            "required": [],
        },
    },
    {
        "name": "get_pro_trending",
        "description": "Get champions trending in pro play — high pick count AND winning record.",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_picks": {"type": "integer", "default": 3},
                "min_wr": {"type": "number", "default": 0.5},
            },
            "required": [],
        },
    },
    {
        "name": "get_synergy",
        "description": "Get synergy score between two champions — how much better they perform together vs individually.",
        "input_schema": {
            "type": "object",
            "properties": {
                "champion_a": {"type": "string"},
                "champion_b": {"type": "string"},
            },
            "required": ["champion_a", "champion_b"],
        },
    },
    {
        "name": "get_team_synergy",
        "description": "Get all pairwise synergy scores for a team composition.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of champion names on the team",
                },
            },
            "required": ["team"],
        },
    },
    {
        "name": "get_candidate_synergy",
        "description": "Check how well a candidate champion synergizes with the existing team picks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate": {"type": "string", "description": "Champion being considered"},
                "existing_team": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Current teammates already picked",
                },
            },
            "required": ["candidate", "existing_team"],
        },
    },
    {
        "name": "get_patch_notes",
        "description": "Get patch notes text for a specific patch version. Useful for understanding recent champion changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {"type": "string", "description": "Patch version like '16.7'"},
            },
            "required": ["patch"],
        },
    },
    {
        "name": "search_patch_context",
        "description": "Semantic search over patch notes. Finds relevant patch note sections for a query like a champion name or gameplay concept (e.g. 'tank items' or 'Corki buffs'). More targeted than reading full patch notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for, e.g. 'Aurora buffs' or 'bot lane item changes'"},
                "n_results": {"type": "integer", "description": "How many results to return", "default": 5},
                "patch": {"type": "string", "description": "Limit to a specific patch version (optional)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_champion_patches",
        "description": "Find all recent patch note changes for a specific champion across patches.",
        "input_schema": {
            "type": "object",
            "properties": {
                "champion": {"type": "string", "description": "Champion name"},
                "n_results": {"type": "integer", "default": 3},
            },
            "required": ["champion"],
        },
    },
]


class ToolExecutor:
    """Executes tool calls from the LLM against the analytics layer."""

    def __init__(
        self,
        champion_stats: ChampionStats,
        pro_meta: ProMetaAnalyzer,
        synergy: SynergyCalculator,
        counter_pick: CounterPickAnalyzer,
        patch_notes: dict[str, str] | None = None,
        patch_index: PatchIndex | None = None,
    ):
        self.champion_stats = champion_stats
        self.pro_meta = pro_meta
        self.synergy = synergy
        self.counter_pick = counter_pick
        self.patch_notes = patch_notes or {}
        self.patch_index = patch_index

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """Run a tool and return the result as a JSON string."""
        log.info(f"executing tool: {tool_name}({tool_input})")

        if tool_name == "get_champion_stats":
            result = self.champion_stats.get_stats(tool_input["champion"])
            return result.model_dump_json() if result else '{"error": "no data for this champion"}'

        elif tool_name == "get_top_champions":
            results = self.champion_stats.top_by_win_rate(
                min_games=tool_input.get("min_games", 5),
                limit=tool_input.get("limit", 15),
            )
            return json.dumps([r.model_dump() for r in results])

        elif tool_name == "get_matchup_delta":
            result = self.champion_stats.get_matchup_delta(
                tool_input["champion"], tool_input["opponent"],
            )
            return result.model_dump_json() if result else '{"error": "no matchup data"}'

        elif tool_name == "get_counter_picks":
            results = self.counter_pick.analyze(
                enemy_picks=tool_input["enemy_picks"],
                role=tool_input.get("role"),
                limit=tool_input.get("limit", 10),
            )
            return json.dumps([r.model_dump() for r in results])

        elif tool_name == "get_pro_presence":
            result = self.pro_meta.get_presence(tool_input["champion"])
            return result.model_dump_json() if result else '{"error": "not picked in pro"}'

        elif tool_name == "get_pro_top_picks":
            results = self.pro_meta.top_picks(limit=tool_input.get("limit", 15))
            return json.dumps([r.model_dump() for r in results])

        elif tool_name == "get_pro_trending":
            results = self.pro_meta.trending_picks(
                min_picks=tool_input.get("min_picks", 3),
                min_wr=tool_input.get("min_wr", 0.5),
            )
            return json.dumps([r.model_dump() for r in results])

        elif tool_name == "get_synergy":
            result = self.synergy.get_synergy(
                tool_input["champion_a"], tool_input["champion_b"],
            )
            return result.model_dump_json() if result else '{"error": "no co-occurrence data"}'

        elif tool_name == "get_team_synergy":
            results = self.synergy.team_synergy(tool_input["team"])
            return json.dumps([r.model_dump() for r in results])

        elif tool_name == "get_candidate_synergy":
            delta = self.synergy.candidate_synergy(
                tool_input["candidate"], tool_input["existing_team"],
            )
            return json.dumps({"candidate": tool_input["candidate"], "synergy_delta": delta})

        elif tool_name == "get_patch_notes":
            patch = tool_input["patch"]
            content = self.patch_notes.get(patch)
            if content:
                return json.dumps({"patch": patch, "content": content})
            return json.dumps({"error": f"no patch notes for {patch}"})

        elif tool_name == "search_patch_context":
            if not self.patch_index:
                return json.dumps({"error": "patch index not built — run `draft index-patches` first"})
            hits = self.patch_index.search(
                query=tool_input["query"],
                n_results=tool_input.get("n_results", 5),
                patch=tool_input.get("patch"),
            )
            return json.dumps(hits)

        elif tool_name == "search_champion_patches":
            if not self.patch_index:
                return json.dumps({"error": "patch index not built — run `draft index-patches` first"})
            hits = self.patch_index.search_champion(
                champion=tool_input["champion"],
                n_results=tool_input.get("n_results", 3),
            )
            return json.dumps(hits)

        return json.dumps({"error": f"unknown tool: {tool_name}"})
