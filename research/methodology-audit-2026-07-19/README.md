# NFELO methodology-audit research release

This directory preserves the runnable source and fixed aggregate results used by
the independent audit dated 19 July 2026. The full report is
[`../../docs/methodology-audit-2026-07-19.md`](../../docs/methodology-audit-2026-07-19.md).

## Evidence boundary

The audit evaluated repository commit
`b005b42da17269a8908bec5bb6a1102143e13b52` and a fixed scored window from 1960
through 11 July 2026 (46,801 matches). Run the capture programs against a clean
checkout of that commit; the main branch intentionally contains the mechanics
selected by the audit and is therefore a different model release.

The source here reproduces the independent retrospective and sensitivity work.
It does **not** recreate the older five-block nested selection bit-for-bit. The
six fitters and frozen derived dataset named by that earlier research were never
committed. `KEY_RESULTS.json` preserves its reported aggregate alongside an
explicit warning.

The audit evaluator's 0.880568 strict-date result batches the ledger's synthetic
numeric day, including incomplete historical dates. The integrated release
instead follows the report's written instruction to keep incomplete dates
sequential; its generated retrospective log loss is approximately 0.880702.

## Environment

Python programs require the repository dependencies plus `pandas`. The network
evaluator requires a C++17 compiler. The commands below assume this directory is
the current working directory and that `audit-target` is a clean worktree at the
fixed commit:

```bash
git worktree add --detach audit-target b005b42da17269a8908bec5bb6a1102143e13b52
python prepare_matches.py --repo audit-target --output matches.tsv
g++ -O3 -std=c++17 network_eval.cpp -o network_eval
./network_eval matches.tsv --output network_default.tsv
python capture_deployed.py --repo audit-target --output deployed_components.npz
python evaluate_gate.py deployed_components.npz --output gate_results.json
python evaluate_forecasts.py deployed_components.npz --output forecast_results.json
python evaluate_rankings.py \
  --network network_default.tsv \
  --matches matches.tsv \
  --components deployed_components.npz \
  --output ranking_results.json
```

The result-order-invariant date update is selected with
`--simultaneous-day-update` in `network_eval.cpp`. To capture the strict
date-frozen score replay:

```bash
python capture_batch_score.py \
  --repo audit-target \
  --source deployed_components.npz \
  --network network_default.tsv \
  --output batch_components.npz
```

The broad rolling searches are in `search_network.py`,
`search_causal_observation.py` and `search_simultaneous.py`. These are
computationally expensive. Their outputs should be interpreted as searches over
the declared candidate space, not proof of a globally optimal formula.

## Interpretation

Keep these result types separate:

- the preserved original nested historical holdout;
- retrospective replays using final 2026 constants; and
- rolling sensitivity searches that retain some deployed formula constants.

Calendar-year bootstrap intervals are paired but conditional on the selected
models; they do not repeat the complete search inside every resample. Generated
large match-level files are intentionally not committed because the underlying
source remains attributable to its publisher.
