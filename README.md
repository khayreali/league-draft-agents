# league-draft-analyst

A CLI tool that recommends League of Legends draft picks using a multi-agent system. You give it a partial draft state (who's picked, who's banned, what role you need), and it returns a ranked list of recommendations backed by solo queue stats, pro play trends, patch note analysis, and team synergy data.

I built this because I play League and I wanted to see if a multi-agent setup actually helps with draft decisions, or if it's just unnecessary complexity. The answer is somewhere in between — but the hard scenarios (sleeper picks from recent buffs, avoiding nerf traps) are where the multi-agent system genuinely outperforms a single-agent baseline. More on that below.

## does the multi-agent setup actually help?

Here's the comparison across all 15 eval scenarios, broken out by difficulty. Real Claude Haiku calls, synthetic match data.

| Difficulty | System | Top-1 Accuracy | Top-3 Recall | Bad Pick Avoidance | Avg Latency | Avg Tool Calls |
|---|---|---|---|---|---|---|
| Easy (5) | Baseline | 20% | 0.20 | 80% | 47s | 21.8 |
| Easy (5) | Multi-Agent | 20% | 0.40 | 60% | 114s | 16.6 |
| Medium (5) | Baseline | 40% | 0.40 | 80% | 57s | 22.0 |
| Medium (5) | Multi-Agent | 40% | 0.48 | 40% | 126s | 25.0 |
| Hard (5) | Baseline | 40% | 0.43 | 40% | 72s | 26.4 |
| Hard (5) | Multi-Agent | 60% | 0.50 | 80% | 114s | 35.0 |

The multi-agent advantage shows up on hard scenarios, which is where you'd hope it would. Top-1 accuracy goes from 40% to 60%, and bad pick avoidance jumps from 40% to 80%. That bad-pick number matters most in practice — recommending a recently-nerfed champion is actively harmful, not just suboptimal.

On easy and medium scenarios the picture is more mixed. Multi-agent gets better recall across the board (0.40 vs 0.20 on easy, 0.48 vs 0.40 on medium) but worse bad-pick avoidance. The multi-agent system is more adventurous — more specialists means more candidate picks, which helps recall but also means occasionally recommending something dumb. For easy drafts, the baseline's conservatism is actually the right strategy.

The standout scenario was `sleeper_buff_pickup` (hard) where multi-agent hit 1.00 recall — found all three expected picks (Orianna, Corki, Twisted Fate) vs baseline's 0.67. That's the scenario that justifies the whole multi-agent setup: the patch context agent flags the Corki buff, the pro meta agent notices TF trending, and the head coach synthesizes them into a coherent recommendation.

The first run hit Anthropic's rate limits and 7 multi-agent scenarios errored out (all 5 easy + 2 medium). I added a 20-second sleep between scenarios, bumped the retry count to 3, and reran the failures. The merged results are what the table shows.

Cost tradeoff: multi-agent is about 1.6x slower and uses ~35 tool calls on hard scenarios vs ~26 for baseline. The parallel specialist execution keeps it from being 3x.

## what it does

The system has four specialist agents that each look at the draft from a different angle:

- **Stats Agent** pulls solo queue win rates, pick rates, and matchup deltas. Uses Wilson score intervals so small sample sizes don't trick it into recommending a 100% WR champion with 3 games.
- **Pro Meta Agent** looks at what's being picked and winning in professional play — LCK, LPL, LEC, LCS. If pros are suddenly prioritizing a champion, there's usually a reason.
- **Patch Context Agent** reads recent patch notes via RAG (ChromaDB) to find champions that were buffed or nerfed. This is the one that catches things the stats haven't caught up to yet.
- **Synergy Critic** evaluates whether a candidate actually fits your team comp. A statistically great pick that clashes with your teammates is worse than a good pick that completes the composition.

These run in parallel via a LangGraph StateGraph, and a Head Coach agent synthesizes their outputs into a final recommendation. The Head Coach cites which agent contributed which insight, so you can see why it's recommending what it is.

There's also a single-agent baseline that gets all the same tools but runs as one ReAct loop. The eval harness compares the two, which is the whole point of the project — proving the orchestration is worth it.

## setup

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), a Riot Games API key, and an Anthropic API key.

```bash
git clone https://github.com/yourusername/league-draft-analyst.git
cd league-draft-analyst
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
draft ingest --since 2026-03-01 --platforms kr,na1 --max-players 10
draft index-patches
```

The ingestion pipeline fetches challenger/GM matches from each region, caches everything in SQLite, and the patch indexer chunks the notes into ChromaDB for retrieval. If you don't have a Riot API key, the system generates synthetic match data automatically so you can still test the agents.

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

**LangGraph** for the multi-agent orchestration because it's the standard for this pattern and it handles the fan-out/fan-in cleanly. I'm using `StateGraph` directly with `Annotated[list, operator.add]` for merging parallel agent outputs. No wrappers.

**Baseline first.** I built the single-agent system before the multi-agent one. This forced me to be honest about scoping — if the baseline already handles a scenario well, adding agents for it is just complexity. The hard eval scenarios are specifically designed around cases where a single agent misses things.

**Four agents, not more.** I went back and forth on whether to add a "team composition archetype" agent but decided against it. The synergy critic already covers comp fitness, and a fifth agent would be padding. The head coach synthesis step is where the magic happens anyway.

**Wilson score intervals** instead of raw win rates for the stats rankings. With small sample sizes, raw percentages are misleading — a champion with 5 wins in 5 games isn't necessarily better than one with 500 wins in 1000. The Wilson lower bound handles this correctly and it's like 5 lines of code.

**SQLite for caching, ChromaDB for RAG.** I don't need Postgres for ~200 match records. SQLite handles the match data and API response caching, ChromaDB handles the patch note embeddings. Anything more would be overengineering.

## eval scenarios

15 scenarios across three difficulty levels:

- **Easy** (5): obvious meta picks where any reasonable system should get it right. Tank jungle when your team is all damage, engage support when your team has none.
- **Medium** (5): requires balancing two perspectives. Best counter-pick doesn't synergize with your team. Pro meta disagrees with solo queue stats.
- **Hard** (5): the ones that justify the multi-agent setup. Corki got buffed in 16.7 but stats haven't caught up — the patch agent and pro meta agent need to agree despite the stats agent missing it. Ambessa was nerfed but her stats still look good from pre-nerf games. A team comp puzzle that requires AP damage AND engage AND surviving the enemy comp.

The hard scenarios are the whole point. If the multi-agent system doesn't beat the baseline there, the project is incomplete.

## what surprised me

The multi-agent system recommended Galio and Ryze for the first easy scenario — champions that aren't even in the synthetic match data. The LLM hallucinated picks from its training data instead of sticking to tool outputs. The baseline did this too (Braum top lane...) but less often. More agents = more chances for at least one to go off-script. Probably need to add the champion pool to the system prompt so it knows what's in the data.

The first eval run was a disaster. 7 of 15 multi-agent scenarios returned empty because three parallel specialists were hammering the Anthropic API and burning through rate limits instantly. Had to add a 20s sleep between scenarios and bump retries to 3. The kind of thing that's obvious in retrospect.

Bad-pick avoidance on easy/medium scenarios is *worse* for multi-agent (60% and 40%) than baseline (80% both). The multi-agent system is more exploratory — more specialists means more candidate champions get surfaced, including questionable ones. For straightforward drafts the baseline's conservatism actually wins. I didn't expect that tradeoff.

## limitations and what's next

The eval was run on synthetic match data — 200 generated matches with seeded champion strength and synergy biases (see `context.py`). There's no Riot API key configured for ingestion, so the analytics layer is working with fake numbers. This means the absolute performance of both systems is worse than it would be with real data, and the synthetic biases could in principle favor one system over the other. Re-running on real ingested match data is the obvious first step.

On cost: multi-agent averaged ~35 tool calls per hard scenario vs ~26 for baseline, and was about 1.7x slower. Each specialist runs its own ReAct loop (with separate LLM calls), plus the synergy critic evaluates up to 8 candidates, plus the head coach synthesis. With Sonnet instead of Haiku, you're looking at a meaningful cost difference per recommendation. The smart move would be routing — classify draft complexity upfront (how many enemy picks are known, whether the patch had major changes) and only run the full multi-agent flow when it matters. Easy drafts go straight to baseline.

One thing I'd rethink entirely: the synergy calculator. Right now it's pure co-occurrence win rate — "Sejuani and Aurora win 65% when on the same team." It can't tell you *why*. A better version would track specific interaction types — CC chains, peel-hypercarry combos, engage follow-up. That kind of structure would make the synergy critic's evaluations much sharper.

I'd also add LLM-as-judge scoring for the eval. Right now it checks champion names but not reasoning quality. The head coach produces great cited reasoning (e.g. "patch: 59% WR +3 AD buff, pro: 40% PR 60% WR") but the eval doesn't score that at all. A judge prompt checking whether reasoning cites concrete tool data would catch cases where the system gets the right answer for the wrong reasons.

## running tests

```bash
uv pip install pytest pytest-asyncio
uv run pytest tests/ -v
```

18 tests covering the rate limiter, analytics layer (Wilson intervals, champion stats, matchup deltas, synergy, counter-picks, pro meta), and agent layer (parallel specialist execution, head coach degraded-input handling).
