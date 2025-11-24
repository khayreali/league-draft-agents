from pydantic import BaseModel


class Champion(BaseModel):
    id: str
    name: str
    key: int
    tags: list[str] = []


class DraftState(BaseModel):
    """Current state of a draft — who's picked, who's banned, what role we need."""
    patch: str
    user_team_picks: list[str] = []
    enemy_team_picks: list[str] = []
    bans: list[str] = []
    user_role: str  # top, jungle, mid, bot, support
    rank: str = "emerald+"


class MatchData(BaseModel):
    match_id: str
    patch: str
    region: str
    is_pro: bool
    winning_team: list[str]
    losing_team: list[str]
    duration_seconds: int
    timestamp: int


class PatchNote(BaseModel):
    patch: str
    content: str
    champions_mentioned: list[str] = []


class Recommendation(BaseModel):
    champion: str
    score: float
    reasoning: str
    sources: list[str] = []  # which agent(s) contributed


class AgentOutput(BaseModel):
    agent_name: str
    recommendations: list[Recommendation] = []
    raw_reasoning: str = ""
    tool_calls_made: int = 0


class EvalScenario(BaseModel):
    name: str
    description: str
    draft_state: DraftState
    expected_good_picks: list[str]
    expected_bad_picks: list[str] = []
    difficulty: str  # easy, medium, hard


class EvalResult(BaseModel):
    scenario_name: str
    system_name: str
    recommendations: list[Recommendation]
    top_pick_quality: bool
    top_3_recall: float
    bad_pick_avoidance: bool
    reasoning_quality: float | None = None
    latency_ms: float
    tool_call_count: int
