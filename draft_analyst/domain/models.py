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
