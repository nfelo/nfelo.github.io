# Model validation

This document separates the evidence for NFELO into three categories. They must
not be combined into a single leaderboard:

1. **Nested historical holdout** — choices use earlier periods and are scored
   on later periods.
2. **Retrospective full-history replay** — final constants are replayed through
   the past to diagnose mechanics.
3. **Prospective** — a forecast is recorded before its result is known.

Three-way logarithmic loss is primary because it evaluates the complete win,
draw and loss vector and penalises unjustified certainty. Brier score, ranked
probability score, accuracy and calibration are secondary.

## Primary evidence: nested historical holdout

The original five-block evaluation contains 46,801 predictions from 1960
onward. Each outer block was scored after model choices had been made using an
earlier period.

| Candidate | Log loss | Most-likely outcome correct |
| --- | ---: | ---: |
| NFELO full-covariance network, two forecast temperatures | **0.884219** | 59.095% |
| Best tested scalar Elo | 0.892970 | 58.527% |
| G-Elo comparison | 0.895187 | 58.779% |
| Published World Football Elo forecast | 0.902619 | 58.804% |

The original report found that the NFELO network beat the published WFER
forecast by 0.018400 log loss per match, with a paired calendar-year interval
of 0.015270–0.021477 in NFELO's favour.

This remains the primary comparative evidence. Its limitation is
reproducibility: the exact fitter programs and frozen derived evaluation
dataset named by the original report were never committed. The aggregate
result and hashes survive, but the selection cannot presently be reconstructed
bit-for-bit.

## Independent methodology audit

The 19 July 2026 audit reconstructed the deployed chronology and ran more than
7,000 additional fold fits or full-history replays. Its main conclusions were:

- retain full opponent covariance;
- retain the goal-margin model and active-pool debut prior;
- retain a common state-update information ratio across competitive classes;
- retain two friendly/competitive probability temperatures;
- do not replace the frozen core constants with unstable fold winners;
- forecast complete dates from one frozen pre-date state;
- update the Gaussian network jointly after the date;
- freeze the attack/defence state until every same-date forecast is stored;
- replace full forecast reversion with the boundary gate;
- reconcile the exact-score matrix with final W/D/L; and
- begin an immutable prospective forecast record.

The audit did not support Dixon–Coles when log loss remained primary, a new
global core fit, different competitive update ratios, or a retrospective
replacement of the existing score-state release schedule.

### Tournament classification and friendly-information fit

The friendly/competitive decision is separate from the source importance
level. A three-state registry classifies tournaments as friendly, competitive
or uncertain. Only positive friendly evidence receives the reduced information
ratio; uncertain and unknown competitions are operationally competitive.

The historical map contains 20,688 friendly matches, 29,910 competitive
matches and 1,714 uncertain matches. The Independence Tournament and Merdeka
Tournament source codes are included as friendlies using the international
friendly-tournament archive and AFC classification evidence.

The full 52,312-match replay scored 46,801 forecasts from 1960 through
11 July 2026. Joint fitting selected:

| Parameter | Value |
| --- | ---: |
| Friendly information ratio | 0.76064 |
| Friendly network temperature | 0.890357703717 |
| Competitive network temperature | 1.060042606190 |

Network-only retrospective log loss was 0.881383694951. At the previously
deployed ratio of 0.75185, with temperatures refitted under the same
classification, it was 0.881384414078.

This is a full-sample retrospective fit. It is reproducible to the fixed ledger
and objective, but it is not a new nested out-of-period result. The original
nested historical holdout remains the primary comparison against other rating
systems.

### Core ablations

| Audit change from the deployed network | Log-loss difference | 95% paired interval |
| --- | ---: | ---: |
| Diagonal covariance | +0.005430 | +0.004108 to +0.006928 |
| No goal-margin information | +0.002388 | +0.000927 to +0.003665 |
| No successor continuity | +0.001078 | +0.000464 to +0.001833 |
| Joint order-invariant date update | −0.000059 | −0.000365 to +0.000221 |

The joint date result is statistically tied on log loss but removes unknown
kickoff-order leakage and arbitrary row-order dependence, so it is preferred
as a structural correction.

## Chronological mechanics

For every complete date, NFELO:

1. computes one pre-date debut prior;
2. initialises all same-date debutants from that prior;
3. applies participant drift and breadth decay once;
4. forecasts all network and score-layer outcomes from the frozen state;
5. applies one joint Gaussian precision update from all date observations;
6. updates attack, defence and goal-environment states only after forecasts are
   saved; and
7. records one post-date ranking event per participant.

Rows without a complete month/day stay sequential. Tests cover order
invariance, equal same-date debut priors, covariance symmetry and positive
semidefiniteness.

## Boundary gate and score grid

A full-reversion gate would discard the entire score correction whenever the
linear pool changed the network top pick. The boundary gate retains the largest
safe fraction instead.

| Retrospective gate diagnostic | Log loss | Brier | Accuracy |
| --- | ---: | ---: | ---: |
| Full reversion | 0.880693 | 0.518495 | 59.125% |
| Boundary gate | **0.880660** | **0.518474** | 59.125% |

Under the audit's strict-date implementation, the boundary-minus-reversion
log-loss interval was −0.000083 to −0.000001 while every top pick remained
identical.

The displayed exact-score matrix is raked by outcome region:

```text
P*(i,j) = Praw(i,j) × Pfinal(outcome) / Praw(outcome)
```

This leaves relative scorelines within wins, draws and losses unchanged while
making the full score matrix agree exactly with the displayed W/D/L vector.
Tail mass is included before the visible 0–5 grid is truncated.

## Retrospective full-history replay

Each build computes a final-layer diagnostic directly from stored pre-match
rows through the fixed 11 July 2026 cutoff. Under the published classification
and constants, the Python replay produces:

| Diagnostic | Value |
| --- | ---: |
| Final-layer log loss | 0.880065 |
| Network-only log loss | 0.881427 |
| Final-layer Brier score | 0.518203 |
| Final-layer ranked probability score | 0.172454 |
| Most-likely outcome correct | 59.103% |
| Matches | 46,801 |

The 2026 annual calibration uses 7,922 matches from 2018–2025 and produces
draw log tilt 0.150867, friendly calibration power 0.915748, competitive
calibration power 1.065716 and network pool weight 0.542471.

These constants and calibrations use information extending beyond parts of the
replay window. The figures diagnose the published chronology and verify the
implementation; they are not nested out-of-sample estimates and do not replace
0.884219 as the headline comparative result.

## Why one public rating was preserved

The audit found that latent posterior-mean gaps were better short-horizon
prediction inputs than the public evidence-adjusted gaps: 0.891291 versus
0.897179 log loss over 43,076 eligible matches. That answers a prediction
question, not the full product question of comparing teams across weakly
connected regions and eras.

If uncertainty shared with a contemporaneous elite reference is cancelled, an
entire isolated cluster can appear precisely placed relative to modern global
football even though the cross-network level is uncertain. In a test configuration,
that made England 1912 rate 2229 and placed several pre-First World War British
teams near the top of football history. The mathematically narrower
within-date interval was therefore unsuitable as an all-time public rating.

NFELO retains one evidence-adjusted rating:

```text
M_i  = 2000 + rho_i × (mu_i - B)
NR_i = M_i - 1.6448536269514715 × sqrt(Sigma_ii)
```

That rating and the match forecast deliberately use different views of the
same network state. The rating applies opponent-breadth shrinkage and a
conservative marginal-uncertainty deduction so rankings remain credible across
uneven schedules and eras. The forecast uses the latent strength difference,
its covariance, venue and the probability-only attack/defence state. A higher
public rating therefore does not guarantee a higher win probability in a
particular match; forcing that agreement would discard tested predictive
information.

The marginal uncertainty deliberately preserves common-mode network
uncertainty. No manual era penalty, British-team cap or result override is
used.

### Historical regression result

Against the rollback baseline on the same 52,310-match source snapshot:

- all 222 current teams kept exactly the same rank;
- mean absolute current-rating movement was 0.036 points;
- maximum current-rating movement was 1.085 points;
- the top 20 nation peaks remained in exactly the same order;
- mean absolute peak movement was 0.373 points; and
- maximum peak movement was 3.872 points.

The leading peaks remained Spain 2010, Brazil 1999, England 1912, Hungary 1955
and France 2001. Only one pre-First World War British nation appeared in the
top 20. Persistent tests check both the public-rating formula and these
historical guardrails.

## Prospective evidence

`source/prospective_forecasts.jsonl` stores the first forecast published for
each identified future fixture and methodology version. Each row includes the
publication time, results-through date, source and model-state hashes, teams,
competition, venue context, public ratings and W/D/L vector.

The file is append-only under normal builds: an existing fixture/model identity
is never overwritten. This provides the clean evidence needed to evaluate the
complete released system without reconstructing probabilities with hindsight.

## Reproduction

The complete audit report is in
`docs/methodology-audit-2026-07-19.md`. Executable audit programs and recorded
results are under `research/methodology-audit-2026-07-19/`.

Routine site builds execute the deployed replay and public regression suite.
The research programs are retained for independent inspection; broad parameter
searches are not rerun during scheduled updates.

## Limitations

NFELO uses results, scores, dates, venue, competition class and declared
identity continuity. It does not use squads, injuries, red cards, tactics,
travel, rest, weather or betting markets. Hard successor mappings and cross-era
comparisons remain modelling assumptions. Bootstrap intervals are conditional
on fitted candidates and do not reproduce complete model selection.
