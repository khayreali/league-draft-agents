# comparison v2 notes

v1 had 7 errored multi-agent scenarios from rate limiting — all 5 easy and 2 medium. The 5 hard scenarios all completed fine in v1 so the hard-scenario numbers didn't change. I added a 20s sleep between scenarios and bumped the Anthropic client to 3 retries, then reran just the 7 failures. All 7 completed this time.

## v2 results (full 15 scenarios)

Hard scenarios are unchanged from v1 since they never errored. Multi-agent still wins: 60% vs 40% top-1, 0.50 vs 0.43 recall, 80% vs 40% bad pick avoidance. `sleeper_buff_pickup` is still the star at 1.00 recall.

Easy scenarios are interesting. Multi-agent actually gets better recall (0.40 vs 0.20) but worse bad-pick avoidance (60% vs 80%). Top-1 is tied at 20%. Both systems struggle on easy scenarios more than I expected — haiku on synthetic data just isn't great at picking the "obvious" answer when the stats don't clearly point there.

Medium is similar: tied on top-1 (40%), multi-agent slightly better on recall (0.48 vs 0.40), but worse on bad-pick avoidance (40% vs 80%). The multi-agent system seems to be more adventurous with its picks, which helps recall but hurts bad-pick avoidance on easier scenarios where playing it safe is the right call.

## surprising thing

The multi-agent system recommended Galio and Ryze in `meta_mid_into_squishies` — champions that aren't even in the synthetic match data. The LLM is hallucinating picks based on its training data rather than the tool outputs. The baseline had this problem too (recommending Braum top lane) but less often. More specialist agents = more chances for at least one to go off-script.

## cost

Multi-agent averages ~25 tool calls across all scenarios vs ~23 for baseline. On hard scenarios it's 35 vs 26. Latency roughly 2x (114s vs 72s on hard). The parallel specialist execution helps — without it the gap would be worse.
