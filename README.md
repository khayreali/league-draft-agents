# league-draft-agents

A CLI tool that recommends League of Legends draft picks using a multi-agent system. You give it a partial draft state (who's picked, who's banned, what role you need), and it returns a ranked list of recommendations backed by solo queue stats, pro play trends, patch note analysis, and team synergy data.

I built this because I play League and I wanted to see if a multi-agent setup actually helps with draft decisions, or if it's just unnecessary complexity. Turns out it does help — especially on the harder scenarios where you need to cross-reference multiple sources of information — but it's not a slam dunk everywhere.

## does the multi-agent setup actually help?

Here's the comparison across all 15 eval scenarios, broken out by difficulty. Real Claude Haiku calls, 177 real challenger/GM matches from KR and NA servers.

| Difficulty | System | Top-1 Accuracy | Top-3 Recall | Bad Pick Avoidance | Avg Latency | Avg Tool Calls |
|---|---|---|---|---|---|---|
| Easy (5) | Baseline | 20% | 0.20 | 100% | 36s | 25.2 |
| Easy (5) | Multi-Agent | 60% | 0.30 | 80% | 109s | 37.6 |
| Medium (5) | Baseline | 0% | 0.00 | 100% | 47s | 24.8 |
| Medium (5) | Multi-Agent | 20% | 0.15 | 100% | 88s | 25.4 |
| Hard (5) | Baseline | 0% | 0.07 | 40% | 46s | 25.8 |
| Hard (5) | Multi-Agent | 20% | 0.33 | 80% | 100s | 26.4 |

Overall: multi-agent gets 33% top-1 accuracy vs 7% for baseline, and 26% top-3 recall vs 9%. Bad pick avoidance is close (87% vs 80%) but the multi-agent system wins on hard scenarios specifically — 80% vs 40%.

The baseline just didn't find the right champions most of the time. It would latch onto whatever had the highest raw win rate and recommend that regardless of context. Multi-agent does better because the specialists each surface different candidates, and the head coach can weigh them against each other.

The hard scenario `sleeper_buff_pickup` was the clearest win — multi-agent got 0.67 recall (found 2 of 3 expected picks) where the baseline got 0.00. That's the scenario where Corki got buffed in 16.7 but the stats haven't caught up yet, so you need the patch context agent to flag it. Similarly `three_patch_crossref` went from 0.00 baseline recall to 0.33 multi-agent.

Bad pick avoidance on easy scenarios is actually worse for multi-agent (80% vs 100%). More agents means more candidates get surfaced, and some of them are bad. For straightforward drafts the baseline's conservatism is the right strategy.

Cost: multi-agent is about 2.3x slower (99s vs 43s average) and uses ~30 tool calls vs ~25. On easy scenarios it's 38 tool calls because of all the synergy critic evaluations, which is kind of wasteful. The smart thing to do would be to route easy drafts straight to the baseline.

## what it does

The system has four specialist agents that each look at the draft from a different angle:

- **Stats Agent** pulls solo queue win rates, pick rates, and matchup deltas. Uses Wilson score intervals so small sample sizes don't trick it into recommending a 100% WR champion with 3 games.
- **Pro Meta Agent** looks at what's being picked and winning in professional play — LCK, LPL, LEC, LCS. If pros are suddenly prioritizing a champion, there's usually a reason.
- **Patch Context Agent** reads recent patch notes via RAG (ChromaDB) to find champions that were buffed or nerfed. This is the one that catches things the stats haven't caught up to yet.
- **Synergy Critic** evaluates whether a candidate actually fits your team comp. A statistically great pick that clashes with your teammates is worse than a good pick that completes the composition.

These run in parallel via a LangGraph StateGraph, and a Head Coach agent synthesizes their outputs into a final recommendation. The Head Coach cites which agent contributed which insight, so you can see why it's recommending what it is.

There's also a single-agent baseline that gets all the same tools but runs as one ReAct loop. The eval harness compares the two.

## setup

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), a Riot Games API key, and an Anthropic API key.

```bash
git clone https://github.com/khayreali/league-draft-agents.git
cd league-draft-agents
uv sync
```

Copy the env template and fill in your keys:

```bash
cp .env.example .env
# edit .env with your RIOT_API_KEY and ANTHROPIC_API_KEY
```

Getting a Riot API key: go to [developer.riotgames.com](https://developer.riotgames.com/), sign in with your League account, and you'll get a development key. It expires every 24 hours which is annoying, but it's enough for ingestion. The rate limits (20/sec, 100/2min) are handled automatically.

## usage

Pull match data and patch notes:

```bash
draft ingest --since 2025-03-01 --platforms kr,na1 --max-players 10
draft index-patches
```

The ingestion pipeline fetches challenger/GM matches from each region, caches everything in SQLite, and the patch indexer chunks the notes into ChromaDB for retrieval.

Get a recommendation:

```bash
draft recommend --role mid --patch 16.7 \
  --picks "Aatrox,Sejuani,Jinx,Thresh" \
  --enemy "Gnar,Viego,Syndra,Caitlyn,Lulu" \
  --bans "Yone"
```

Run the single-agent baseline for comparison:

```bash
draft recommend --role mid --patch 16.7 \
  --picks "Aatrox,Sejuani,Jinx,Thresh" \
  --enemy "Gnar,Viego,Syndra,Caitlyn,Lulu" \
  --bans "Yone" \
  --baseline
```

Run the eval:

```bash
draft eval                    # multi-agent system
draft eval --baseline         # single-agent baseline
draft compare                 # both side-by-side
```

The compare command prints three tables: per-scenario results, overall metrics, and a by-difficulty breakdown. It also writes everything to `eval/results.json`.

## architecture

```
                    LangGraph StateGraph
                    
START ──┬── StatsAgent ──────────┐
        ├── ProMetaAgent ────────┤──> HeadCoachAgent ──> final recs
        └── PatchContextAgent ───┘      │
                                        ├── calls SynergyCritic
                                        └── on top candidates
```

Four layers, dependencies flow downward:

**Layer 1 — Data** (`draft_analyst/data/`): Riot API client with async rate limiting (dual token bucket for the 20/sec + 100/2min limits), Data Dragon for static champion data, patch note scraper with local YAML fallback, SQLite for caching, ChromaDB for patch note embeddings.

**Layer 2 — Analytics** (`draft_analyst/analytics/`): Pure Python compute. Champion stats with Wilson score confidence intervals, pro meta analysis (pick trends, comp profiles), pairwise synergy from co-occurrence win rates, counter-pick analysis via matchup deltas. No LLM calls in this layer.

**Layer 3 — Agents** (`draft_analyst/agents/`): Each agent gets a focused system prompt and a subset of the 13 available tools. They run ReAct loops — the LLM calls tools, we execute them against the analytics layer, repeat until the LLM produces recommendations. LangGraph fans out the three specialists in parallel.

**Layer 4 — Evaluation** (`draft_analyst/evaluation/`): 15 hand-curated scenarios spanning easy/medium/hard. The Evaluator scores on top-pick accuracy, top-3 recall, bad-pick avoidance, latency, and tool call count. The ComparisonRunner is the main deliverable — it runs both systems and prints the side-by-side comparison.

## why these choices

**LangGraph** for the multi-agent orchestration because it handles the fan-out/fan-in cleanly. I'm using `StateGraph` directly with `Annotated[list, operator.add]` for merging parallel agent outputs.

**Baseline first.** I built the single-agent system before the multi-agent one. This forced me to be honest about scoping — if the baseline already handles a scenario well, adding agents for it is just complexity. The hard eval scenarios are specifically designed around cases where a single agent misses things.

**Four agents, not more.** I went back and forth on whether to add a "team composition archetype" agent but decided against it. The synergy critic already covers comp fitness, and a fifth agent would be padding.

**Wilson score intervals** instead of raw win rates for the stats rankings. With small sample sizes, raw percentages are misleading — a champion with 5 wins in 5 games isn't necessarily better than one with 500 wins in 1000. The Wilson lower bound handles this correctly and it's like 5 lines of code.

**SQLite for caching, ChromaDB for RAG.** I don't need Postgres for match records. SQLite handles the match data and API response caching, ChromaDB handles the patch note embeddings. Anything more would be overengineering.

## eval scenarios

15 scenarios across three difficulty levels:

- **Easy** (5): obvious meta picks where any reasonable system should get it right. Tank jungle when your team is all damage, engage support when your team has none.
- **Medium** (5): requires balancing two perspectives. Best counter-pick doesn't synergize with your team. Pro meta disagrees with solo queue stats.
- **Hard** (5): the ones that justify the multi-agent setup. Corki got buffed in 16.7 but stats haven't caught up — the patch agent and pro meta agent need to agree despite the stats agent missing it. Ambessa was nerfed but her stats still look good from pre-nerf games. A team comp puzzle that requires AP damage AND engage AND surviving the enemy comp.

## what surprised me

The baseline was worse than I expected. 7% top-1 accuracy is really bad — it only got a single scenario right out of 15 (the `obvious_tank_jungle` one where Jarvan IV is just clearly the best pick statistically). It kept recommending Xerath and Lissandra based on high win rates in the match data even when they didn't fit the scenario at all.

Multi-agent had the opposite problem on easy scenarios. It recommended too many candidates because each specialist surfaced different champions. The head coach would then include some questionable picks in the final list. On `obvious_tank_jungle` the multi-agent system recommended Lee Sin (explicitly a bad pick in that scenario — team needs a tank, not more damage). More agents = more chances for someone to suggest something dumb.

The `sleeper_buff_pickup` scenario was the most satisfying. The baseline had 0.00 recall — it completely missed the Corki buff. The multi-agent system got 0.67 because the patch context agent flagged the base AD and package CD buffs and the head coach weighted that information correctly.

Rate limiting was a pain. The first attempt with Sonnet was basically unusable — constant 429s on a new API key. Switched to Haiku and it worked fine. The Anthropic SDK's built-in retry with backoff handled the occasional 429 gracefully.

## limitations and what's next

The eval scenarios use real match data (177 challenger/GM games from KR and NA) but the patch notes are curated YAML files I wrote, not scraped from an actual source. The wiki scraper in the code doesn't work because the League wiki 403s automated requests and the official site is JS-rendered. So the patch context agent is working with patch notes I wrote by hand. They're accurate but it means the system can't auto-update when new patches drop.

On cost: multi-agent averaged ~30 tool calls per scenario vs ~25 for baseline, and was about 2.3x slower. Each specialist runs its own ReAct loop (with separate LLM calls), plus the synergy critic evaluates up to 8 candidates, plus the head coach synthesis. The smart move would be routing — classify draft complexity upfront and only run the full multi-agent flow when it matters.

One thing I'd rethink is the synergy calculator. Right now it's pure co-occurrence win rate — "Sejuani and Aurora win 65% when on the same team." It can't tell you *why*. A better version would track specific interaction types — CC chains, peel-hypercarry combos, engage follow-up.

I'd also add LLM-as-judge scoring for the eval. Right now it checks champion names but not reasoning quality. The head coach produces cited reasoning but the eval doesn't score that at all.

## running tests

```bash
uv pip install pytest pytest-asyncio
uv run pytest tests/ -v
```

18 tests covering the rate limiter, analytics layer (Wilson intervals, champion stats, matchup deltas, synergy, counter-picks, pro meta), and agent layer (parallel specialist execution, head coach degraded-input handling).
