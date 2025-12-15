# comparison v3 notes

Ran on real match data this time — 177 challenger/GM games from KR (91) and NA (86), pulled via Riot API. Real Claude Haiku calls for both systems. Patch notes are still the curated YAML files since the wiki scraper doesn't work.

## overall

Multi-agent: 33% top-1, 26% recall, 87% bad avoid. Baseline: 7% top-1, 9% recall, 80% bad avoid. Multi-agent wins across the board but neither system is great in absolute terms. Haiku on 177 matches is a tough combo.

## by difficulty

Easy: multi-agent 60% top-1 vs baseline 20%. Multi-agent got 3 of 5 right (meta_mid_into_squishies, standard_bot_lane, engage_support_needed). Baseline only got obvious_tank_jungle. But multi-agent recommended Lee Sin in that scenario which is a bad pick, so bad avoid dropped to 80% vs 100%.

Medium: both systems struggled. Baseline got 0% top-1 across all 5 medium scenarios which is pretty bad. Multi-agent got 1 (late_pick_top_flex). The medium scenarios are designed so you need to balance two competing signals, and neither system does that well.

Hard: this is where the multi-agent advantage matters. Baseline got 0% top-1 and only 0.07 recall — it basically whiffed on all 5 hard scenarios. Multi-agent got 20% top-1 and 0.33 recall. More importantly, bad pick avoidance went from 40% to 80%. The baseline recommended nerfed/bad champions in 3 of 5 hard scenarios.

## standout scenarios

sleeper_buff_pickup: multi-agent 0.67 recall vs baseline 0.00. The patch context agent caught the Corki buff. This is the whole point of the project.

comp_puzzle_engage_ap: both systems found Ahri (the top expected pick) through multi-agent. Baseline also found her (0.33 recall) but recommended Corki who's in the bad list for this scenario (AD not AP).

three_patch_crossref: multi-agent 0.33 recall vs 0.00, and multi-agent avoided the bad picks (LeBlanc, Azir) while baseline recommended both.

## cost

Baseline: 43s avg, 25 tool calls. Multi-agent: 99s avg, 30 tool calls. The multi-agent overhead is mostly on easy scenarios (38 tool calls) because the synergy critic runs on every candidate. On medium/hard it's closer to 26 tool calls which is barely more than baseline.

## vs v2 (synthetic data)

The real data results are directionally similar to the synthetic runs — multi-agent still wins on hard scenarios. But the absolute numbers are different. The baseline is much worse on real data (7% vs 33% top-1 in v2). I think the synthetic data had stronger/cleaner statistical signals that made it easier for a single agent to find the right answer. Real challenger data is noisier — more champion diversity, less obvious meta picks.
