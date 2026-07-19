# Model validation and audit status

This document distinguishes what NFELO's historical tests establish, what they
do not establish and which changes were adopted after the methodology audit of
19 July 2026.

## Evidence labels

NFELO uses three labels and does not treat them as interchangeable:

- **Nested historical holdout:** choices are made on earlier periods and scored
  on later periods that did not choose those settings. This is the primary
  historical evidence.
- **Retrospective full-history replay:** final constants are replayed into the
  past. This is useful for controlled component comparisons, but is optimistic
  as a headline forecast estimate.
- **Prospective:** a forecast is recorded before the result is known and later
  scored unchanged. This is the cleanest evidence for the final all-data model.

## Primary historical comparison

The original research used five chronological outer blocks beginning in 1960.
Model selection used an earlier block and evaluation used the following block.
The combined holdout contains 46,801 match predictions.

| Rolling holdout candidate | Log loss | Most-likely result correct |
| --- | ---: | ---: |
| Common-update full network, two temperatures | **0.884219** | 59.095% |
| Unequal competition update weights | 0.884203 | 59.065% |
| Five forecast temperatures | 0.884286 | 59.095% |
| One forecast temperature | 0.885159 | 59.095% |
| Best tested scalar Elo | 0.892970 | 58.527% |
| Published World Football Elo forecast | 0.902619 | 58.804% |

Lower log loss is better. The tiny numerical advantage for unequal competition
weights was not stable: its paired interval crossed zero, while the common model
was simpler. The release therefore keeps one state-update information ratio for
all competitions. Friendlies and competitive matches still use separate
probability temperatures.

The original report's paired year-cluster interval for NFELO minus published
World Football Elo was 0.015270 to 0.021477 log-loss points in NFELO's favour.
That supports the core architecture. It does not imply that NFELO chooses the
correct W/D/L label dramatically more often; much of the gain is better
probability calibration when the models choose the same label.

### Reproducibility limit

The programs and frozen derived dataset named by the original nested research
were not committed. Its aggregate output and hashes survive, but the exact
selection cannot currently be rerun bit-for-bit. The 0.884219 result is therefore
reported honestly as preserved historical evidence, not as a freshly
reproduced benchmark.

## Independent 2026 audit

The audit rebuilt the deployed replay and ran more than 7,000 fold fits or
full-history replays across network, chronology, score-layer, gate, ranking and
identity alternatives. The principal findings were:

| Change from the full network | Log-loss change | 95% paired interval | Decision |
| --- | ---: | ---: | --- |
| Diagonal rather than full covariance | +0.005430 | +0.004108 to +0.006928 | Reject |
| Remove goal-margin information | +0.002388 | +0.000927 to +0.003665 | Reject |
| Remove predecessor/successor continuity | +0.001078 | +0.000464 to +0.001833 | Reject hard removal |
| Joint order-invariant date update | −0.000059 | −0.000365 to +0.000221 | Adopt structurally |

The wider parameter search did not justify changing the frozen global
constants. Fold winners were unstable and the selected-minus-deployed interval
crossed zero. The audit therefore changed mechanics with clear structural
benefits while retaining the existing core values.

## Adopted strict-date mechanics

Nearly nine in ten evaluation matches shared their calendar date with another
match, while exact kickoff order is frequently unavailable. The replay now:

1. groups all matches with a known complete date;
2. calculates one active-pool prior for every debutant that date;
3. adds drift once per participant;
4. freezes every network and attack/defence forecast before learning a result;
5. adds frozen match information jointly to the Gaussian precision; and
6. applies attack/defence and goal-environment observations only after all
   forecasts on the date have been stored.

The joint update is

```text
Sigma' = [Sigma^-1 + sum_k c_k x_k x_k^T]^-1
mu'    = mu + Sigma' sum_k g_k x_k
```

where each curvature `c_k` and score gradient `g_k` is evaluated from the
shared pre-date state. Reordering same-date rows changes the aggregate replay by
less than numerical round-off. Rows with an unknown historical month or day are
not falsely grouped; they retain their source sequence.

## Forecast layer and boundary gate

The hidden attack/defence layer improved retrospective log loss in every broad
chronological block, but it does not yet have an independently reproducible
nested headline. The current release schedule and eight-year annual calibration
are therefore retained pending a clean nested refit.

The former safety gate discarded the entire score correction whenever the
linear pool changed the network's most likely result. The boundary gate instead
moves from the network vector toward the pooled vector up to the last point at
which the original top label remains top. Under the strict-date replay:

| Audit-evaluator strict-date forecast | Log loss | Accuracy |
| --- | ---: | ---: |
| Joint date update, full-reversion gate | 0.880609 | 59.125% |
| Joint date update, boundary gate | **0.880568** | 59.125% |

The paired 95% interval for boundary minus full reversion was −0.000083 to
−0.000001. The top W/D/L selection is identical by construction. These are
retrospective component diagnostics, not nested estimates.

### Integration erratum: incomplete dates

The audit evaluator grouped rows by the ledger's synthetic numeric `day`. Rows
whose historical month or day is unknown can therefore be grouped together; in
one edge case that number can also coincide with a previous December date. That
does not satisfy the audit's written recommendation that incomplete dates remain
sequential. The deployed implementation follows the written rule. On the same
fixed cutoff its generated log loss is approximately **0.880702**, rather than
0.880568. The exact deployed retrospective value is calculated from match rows
on every build and written to `summary.json`; it is not hard-coded. This small
correction does not affect the nested 0.884219 evidence or the decision to use
complete-date joint updates and the boundary gate.

A tested Dixon–Coles low-score correction worsened primary log loss by 0.000041;
its interval crossed zero. It was not adopted.

## Exact-score reconciliation

Raw independent-Poisson score cells do not include the final draw tilt,
temperatures, network blend and boundary gate. The predictor now rakes the full
score matrix by outcome region:

```text
P*(i,j) = Praw(i,j) × Pfinal(outcome region) / Praw(outcome region)
```

The relative ordering of scorelines within wins, draws and losses is preserved,
while the three region totals exactly match the displayed final W/D/L vector.
Tail mass is included before the interface displays only the 0–5 cells.

## Strength versus conservative records

Testing on 43,076 eligible matches found the latent posterior-mean gap more
predictive than the former breadth-adjusted lower-bound display:

| Pre-match ranking signal | Log loss |
| --- | ---: |
| Posterior mean strength | **0.891291** |
| Mean minus 1.645 raw standard errors | 0.891429 |
| Former public breadth/lower-bound rating | 0.897179 |

The mean-minus-former-public difference was −0.005888, with a paired 95%
interval of −0.007287 to −0.004662. NFELO now publishes posterior mean strength
as the ranking and moves the lower bound to a separately named record score.

With `B` the mean of the ten strongest eligible active latent means, the ranking
is:

```text
Strength_i = 2000 + mu_i - B
```

For the record book, `rho_i = N_i / (N_i + 4)` is based on decayed effective
opponent breadth:

```text
M_i      = 2000 + rho_i (mu_i - B)
Record_i = M_i - 1.644854 SE(M_i)
```

`SE(M_i)` propagates the team's variance, the elite-reference variance and
their covariance, all multiplied by `rho_i`. Combined matchup records use the
analogous full coefficient-vector covariance. Uncertainty caused by selecting
the elite set itself remains an additional limitation.

## Frozen release values

The audit retained the deployed structural constants:

- prior standard deviation: 300;
- drift standard deviation: 19.7502126 per square-root year;
- quality scale: 1.7440261;
- common competition information ratio: 1;
- friendly forecast power: 0.9697407;
- competitive forecast power: 1.0635626;
- the existing era curves, margin curve, active-pool debut formula and score
  release schedule.

Exact machine-readable values remain in `config/elo_matches.json`,
`config/forecast_layer.json` and the generated `public/data/summary.json`.

## Prospective evidence and next research release

The build appends the first published forecast for each identified fixture and
methodology version to `source/prospective_forecasts.jsonl`, including the data
hash, publication time, ratings and W/D/L vector. Later changes do not overwrite
that first forecast.

The next structural refit should be pre-registered and nest the complete choice
inside every outer training period. It should test a small regularised grid
around the retained core; one common score state versus the current schedule;
joint versus sequential score calibration; 8-, 12- and 20-year windows; and
hard rename continuity versus discounted political-successor transfer priors.
It should store immutable row-level predictions, not only aggregate scores.

Until that pipeline exists, the correct release decision is to retain the
current constants, use the audited mechanics and accumulate prospective data.

## What validation cannot prove

The space of possible models is infinite and international football changes
over time. No historical search proves universal optimality or guarantees
future superiority. NFELO also omits squads, injuries, dismissals, tactics,
travel, rest, weather and markets. Validation supports a defined results-only
model under a defined protocol; it does not convert estimates into certainty.
