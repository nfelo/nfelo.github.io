# Model validation

The public site reports one headline for the formula it currently deploys:
46,801 historical pre-match forecasts, log loss 0.878333 and top-result
accuracy 59.170%. That is a retrospective full-history replay. This technical
record preserves three evidence categories behind that headline, which must not
be combined into a single leaderboard:

1. **Nested historical holdout** — choices use earlier periods and are scored
   on later periods.
2. **Retrospective full-history replay** — final constants are replayed through
   the past to diagnose mechanics.
3. **Prospective** — a forecast is recorded before its result is known.

Three-way logarithmic loss is primary because it evaluates the complete win,
draw and loss vector and penalises unjustified certainty. Brier score, ranked
probability score, accuracy and calibration are secondary.

## Archived comparative evidence: nested historical holdout

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

This remains archived comparative evidence for the earlier network
specification. It is not presented as the accuracy of the complete current
formula. Its limitation is reproducibility: the exact fitter programs and
frozen derived evaluation dataset named by the original report were never
committed. The aggregate result and hashes survive, but the selection cannot
presently be reconstructed bit-for-bit.

## Method selection and structural checks

The structural review reconstructed the chronology and ran more than
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

The evidence did not support Dixon–Coles when log loss remained primary, a new
global core fit, different competitive update ratios, or a retrospective
replacement of the existing score-state release schedule.

### Country-specific venue study

The 27 July 2026 venue audit added a separate causal model-selection exercise.
It ran 1,949 overlapping screening fits across 16 additive, swap-invariant
structures, including global drift, country host only, away only, separate
host/away, shared home dependence, neutral and non-home formulations.

Formula and hyperparameter selection used matches through 2019. The 6,320
matches from 2020 through 11 July 2026 were not inspected until the shared
country-dependence structure, 60-point prior, 40-year half-life, unit result
learning and zero neutral adjustment had been fixed.

| End-to-end replay | Log loss |
| --- | ---: |
| Previous final layer | 0.880169 |
| Selected country-profile final layer | **0.878333** |
| Improvement | **0.001836** |

The untouched 2020–2026 improvement was 0.001315. A paired year-block
bootstrap put its 95% interval at 0.000208–0.002607, with 99.0% of resamples
favouring the country model. Every one of the five main time blocks improved.

The ledger lists the host first in 38,769 non-neutral rows and second in only
one, so unrestricted country host and visitor effects are not cleanly
identified. The adopted value is therefore split equally between hosting
benefit and away disadvantage. Separate host/away states were tested and
improved the baseline, but by less. Adding a country-specific neutral state or
adding venue posterior variance to match variance weakened the stronger model.

The full protocol, screening-family table, formulae and guardrails are in
`research/home-advantage-2026-07-27/`.

### Tournament classification and friendly-information fit

The friendly/competitive decision is separate from the source importance
level. A three-state registry classifies tournaments as friendly, competitive
or uncertain. Only positive friendly evidence receives the reduced information
ratio; uncertain and unknown competitions are operationally competitive.

The historical map contains 21,529 friendly matches, 30,165 competitive
matches and 618 uncertain matches. The fallback Other tournaments category has
been reviewed code by code: 72 source codes are friendly invitationals or
preparation events, while 16 are formal competitions.

The full 52,312-match replay scored 46,801 forecasts from 1960 through
11 July 2026. Joint fitting selected:

| Parameter | Value |
| --- | ---: |
| Friendly information ratio | 0.78621 |
| Friendly network temperature | 0.896294991479 |
| Competitive network temperature | 1.061356232973 |

Network-only retrospective log loss is 0.881475145850. At the previous ratio
of 0.76064, with temperatures refitted under the same classification, it is
0.881478166958.

This is a full-sample retrospective fit. It is reproducible to the fixed ledger
and objective, but it is not a new nested out-of-period comparison against
other rating systems.

An additional temporal check tested 1,650 constant, step and smooth
era-varying friendly ratios. Candidate families were selected on 2010–2019
after fitting temperatures only through 2009, then confirmed on untouched
2020–2026 matches. Every flexible family winner was worse than the deployed
constant on confirmation; deterioration ranged from 0.000050 to 0.000565 log
loss. A separate 170-profile venue-learning check found only 0.000022
incremental gain for a smooth era trend over its best single constant, with a
paired year-block interval crossing zero. The release therefore retains one
`0.78621` friendly information ratio in both updates.

### Core ablations

| Ablation | Log-loss difference | 95% paired interval |
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
4. projects participant country venue states to the date;
5. forecasts all network and score-layer outcomes from the frozen state;
6. applies one joint Gaussian precision update from all date observations;
7. updates country venue, attack, defence and goal-environment states only
   after forecasts are saved; and
8. records one post-date ranking event per participant.

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

Under the strict-date implementation, the boundary-minus-reversion
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
| Final-layer log loss | 0.878333 |
| Network-only log loss | 0.879921 |
| Final-layer Brier score | 0.517162 |
| Final-layer ranked probability score | 0.171949 |
| Most-likely outcome correct | 59.170% |
| Matches | 46,801 |

The annual calibration uses 7,922 matches from
2018–2025 and
produces draw log tilt 0.151744, friendly calibration
power 0.905675, competitive calibration power
1.067154 and network pool weight
0.531124.

The four fitted values are canonicalised to six decimal places before they are
used or published. This grid is far below the site's displayed probability
precision and prevents different CPU math libraries from turning an identical
fit into a different final digit.

These constants and calibrations use information extending beyond parts of the
replay window. The figures diagnose the published chronology and verify the
complete current implementation. They supply the public current-formula
headline, explicitly labelled as retrospective rather than nested
out-of-sample evidence.

## Why one public rating was preserved

Latent posterior-mean gaps were better short-horizon
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

Historical rankings are reconstructed from compact global end-of-day network
snapshots, not by carrying each team’s own last-match point forward. This is
necessary because a full-covariance update can move a connected non-participant.
The release audit requires Current Rankings and the latest History table to
have the same membership, order and public values, and checks every No. 1 spell
against the top History row on its entry date.

### Historical guardrails

The preceding global-as-of consistency release was checked against its
rollback baseline on the same 52,310-match source snapshot:

- all 222 current teams kept exactly the same rank;
- mean absolute current-rating movement was 0.036 points;
- maximum current-rating movement was 1.085 points;
- the top 20 nation peaks remained in exactly the same order;
- mean absolute peak movement was 0.373 points; and
- maximum peak movement was 3.872 points.

Those checks remain in the suite. After the country-venue release, the leading
peaks are Brazil 1999, Spain 2012, England 1912, Hungary 1955 and France 2001.
Only one pre-First World War British nation appears in the top 20. Persistent
tests check both the public-rating formula and these historical guardrails.

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
The later country venue study is under
`research/home-advantage-2026-07-27/`.

Routine site builds execute the deployed replay and public regression suite.
The research programmes are retained for independent inspection; broad parameter
searches are not rerun during scheduled updates.

## Limitations

NFELO uses results, scores, dates, venue, competition class and declared
identity continuity. It does not use squads, injuries, red cards, tactics,
travel, rest, weather or betting markets. Hard successor mappings and cross-era
comparisons remain modelling assumptions. Bootstrap intervals are conditional
on fitted candidates and do not reproduce complete model selection.
