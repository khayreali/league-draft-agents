import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DB = DATA_DIR / "cache.db"
CHROMA_DIR = DATA_DIR / "chroma"

RIOT_API_KEY = os.getenv("RIOT_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# riot rate limits: 20 requests per second, 100 per 2 minutes
RIOT_RATE_LIMIT_PER_SECOND = 20
RIOT_RATE_LIMIT_PER_2MIN = 100

DEFAULT_REGIONS = ["kr", "euw1", "na1"]
PRO_LEAGUES = ["LCK", "LPL", "LEC", "LCS"]

# llm defaults
# sonnet for agents by default; eval run used haiku for cost
DEFAULT_AGENT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_CHEAP_MODEL = "claude-haiku-4-5-20251001"
