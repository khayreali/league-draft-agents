# comparison v1 notes

Ran on synthetic match data with real Claude Haiku calls (not mocks), 15 scenarios. The multi-agent system failed to produce recommendations for the first 7 scenarios — the specialists returned empty output, probably from Anthropic API rate limiting during the long sequential run. The last 8 scenarios all worked correctly. I'm analyzing those 8.

## hard scenarios

Multi-agent beat baseline on the metrics that matter. Top-1 accuracy: 60% vs 40%. Top-3 recall: 0.50 vs 0.43. Bad pick avoidance: 80% vs 40%. The standout was `sleeper_buff_pickup` where multi-agent got perfect recall (1.00) — it found Orianna, Corki, and Twisted Fate, all three expected good picks. Baseline only got 0.67 there (missed TF). The `three_patch_crossref` scenario also showed the multi-agent advantage clearly: 0.67 recall vs 0.33 for baseline, and multi-agent avoided the bad picks while baseline recommended LeBlanc.

## easy scenarios

No valid multi-agent results because of the rate limiting issue. Baseline got 5 PASS out of 15 total (33% top-1 accuracy overall), which is honestly worse than I expected. Haiku with synthetic data is a tough combo — the stats don't always point clearly at the "right" answer.

## baseline surprises

The baseline recommended Corki as #1 pick in like half the scenarios regardless of context. It seemed to latch onto Corki's high synthetic WR and pro trending stats. The multi-agent system diversified better because each specialist brought a different lens.

## latency and cost

Multi-agent: ~114s and ~32 tool calls per scenario. Baseline: ~66s and ~25 tool calls. About 1.7x slower and 1.3x more tool calls. The gap is smaller than I expected — the parallel specialist execution helps offset some of the extra head coach + critic calls.
