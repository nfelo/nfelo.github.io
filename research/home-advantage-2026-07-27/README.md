# Country-specific venue effects audit

**Study date:** 27 July 2026

**Ledger:** 52,316 senior men’s internationals, 1872–2026

**Scoring window:** 46,801 matches, 1960–11 July 2026

**Primary score:** pre-match three-way win/draw/loss log loss

**Decision:** adopt one causal, time-varying country home-dependence state

## Executive finding

Countries do not appear to share one fixed home effect. A causal country term
improves probability forecasts after the existing era-wide home baseline has
already been applied.

The strongest identifiable structure is not an unrestricted pair of separate
“home strength” and “away weakness” parameters. It is one country
home-dependence value, split equally between the team’s hosting boost and its
away penalty. The value changes through time and reverts toward zero with a
40-year half-life.

The selected end-to-end model lowered final-layer retrospective log loss from
`0.88016905` to `0.87833346`, an improvement of `0.00183559`. On the 6,320
matches from 2020 onward that were not used to select the formula or
hyperparameters, it improved log loss by `0.00131545`. The paired year-block
bootstrap interval for that untouched improvement was `0.00020757` to
`0.00260743`, with 99.024% of resamples favouring the country model.

No country-specific neutral-site adjustment was adopted. It did not improve
the strongest model.

## Why home and away cannot be fitted freely

The result ledger has the following venue/order structure:

| Source relationship | Matches |
| --- | ---: |
| Host listed as team one | 38,769 |
| Host listed as team two | 1 |
| Neutral venue | 13,546 |

If country A hosts country B, an unexpectedly strong home result can be
described as:

- an unusual hosting benefit for A;
- an unusual visitor disadvantage for B; or
- a combination of both.

With essentially no reversal of host ordering, the two unrestricted parameter
sets are weakly identified. They can trade off against one another while
producing very similar fitted match differences. Regularisation makes a
separate host/away model estimable, but not as stable or accurate as the shared
country dependence value.

This is a property of the available evidence, not a claim that hosting and
travelling are physically identical mechanisms.

## Protocol

The audit preserved every existing NFELO component:

- the full opponent-network covariance;
- era-specific strength scale, worldwide home baseline and draw rate;
- causal same-date batching;
- friendly information ratio `0.78621`;
- goal-margin environment;
- public breadth and uncertainty adjustment; and
- hidden attack/defence forecast with annual prior-years-only calibration.

The search added only venue residual states. Every candidate:

1. predicted a complete date from the state available before that date;
2. learned venue evidence only after every forecast for that date was frozen;
3. remained invariant when team order and the home sign were reversed;
4. used no future match to estimate an earlier profile; and
5. was evaluated on the same 46,801 scored matches.

The fast screening stage held the already deployed opponent-network chronology
fixed. This made a wide structural search feasible without allowing one
candidate’s changed ratings to contaminate another candidate’s comparison.
The selected candidate was then run through the complete rating and scoring
replay.

## Formula families tested

The search executed 1,949 valid, overlapping screening fits across 16
structures and refinements. Families included:

- a time-varying global residual;
- country host only;
- country away only;
- separate country host and away states;
- a shared country home-dependence state;
- country neutral-site asymmetry;
- one country non-home state shared by away and neutral matches;
- combinations of global, host, away and neutral terms; and
- the shared dependence model with and without a neutral state.

For the strongest families, the search varied:

- prior standard deviations from 30 to 90 Elo points;
- half-lives from 10 years to static;
- unit result learning, all-match unit learning and the full
  network/goal-margin learning weight; and
- 0%, 25%, 50% and 100% of venue posterior variance added to predictive
  match variance.

“All possible formulae” cannot literally be enumerated. The search covers the
main additive, swap-invariant, causally estimable decompositions supported by
the venue fields in this ledger. More complex geography, altitude, climate,
travel-distance and venue-level models would require reliable covariates not
present in the source.

## Screening results

The table reports lower-is-better log-loss improvement over the era-only home
baseline. Positive values are improvements.

| Best member of family | All scored matches | 2020–2026 |
| --- | ---: | ---: |
| Global dynamic residual only | 0.000238 | **−0.000098** |
| Country host only | 0.000876 | 0.001081 |
| Country away only | 0.000829 | 0.000752 |
| Separate country host + away | 0.001230 | 0.001357 |
| Global + separate host + away | 0.001291 | 0.001176 |
| Shared country dependence + neutral | 0.001237 | 0.000892 |
| Shared dependence extended to non-home matches | 0.001583 | 0.001196 |
| Global + shared dependence | 0.001612 | 0.001371 |
| **Shared country dependence, home matches only** | **0.001662** | **0.001410** |

The global-only residual worsened the untouched period. The signal is therefore
not merely an omitted modern worldwide home trend.

The neutral extensions weakened the shared home model. A neutral-only model
found a very small retrospective gain, but it was far below the selected
effect, vulnerable to first/second source ordering and did not improve the
combined specification. Neutral was fixed to zero.

## Hyperparameter selection

Candidate choice used matches through 2019. The 2020–2026 block was not
inspected until after the formula and parameters were fixed.

The selected screening specification was:

| Parameter | Selected value |
| --- | ---: |
| Structure | Shared country home dependence |
| Prior standard deviation | 60 Elo points |
| Temporal half-life | 40 years |
| Competitive learning ratio | 1 |
| Friendly learning ratio | 0.78621 |
| Venue predictive-variance scale | 0 |
| Neutral effect | 0 |

The result is on a broad plateau. For example, using the same unit-learning
rule, prior 60 with half-lives 40, 50 and 60 years improved all-period
screening log loss by `0.00166206`, `0.00166583` and `0.00166476`
respectively. Prior values 55–65 and half-lives 35–80 also remained close.
The 40-year value won the declared through-2019 selection; the slightly better
full-period 50-year fit was not substituted after seeing later results.

Adding venue posterior variance to the match variance never beat the
zero-addition candidate in the local search. Posterior means are already
shrunk toward zero according to their uncertainty, so adding that variance
again was empirically harmful.

## Friendly information by era

The audit also tested whether the `0.78621` friendly information ratio should
change through time. This was checked separately in the main strength network
and in the country venue update.

For the main network, 1,650 candidate curves covered constants, one-change
steps, three-era steps, smooth long-run trends and five-knot smooth functions,
with ratios from 0.20 to 1.40. Curves were selected on 2010–2019 after
probability temperatures had been fitted only through 2009. One winner from
each family was then refitted through 2019 and scored on the untouched
2020–2026 block.

Every flexible family winner became worse than the deployed constant on that
untouched block. The smallest deterioration was `0.000050` log loss for the
best two-era step; the five-knot and three-knot winners deteriorated by up to
`0.000565`. Even the best newly selected single constant deteriorated by
`0.000074`. The apparent era patterns therefore did not travel forward.

The country venue update received a separate 170-profile check. Its strongest
smooth trend improved untouched log loss by `0.000070` against the deployed
venue-learning constant, but simply lowering one constant produced
`0.000048` of that gain. The incremental era component was only `0.000022`.
A paired year-block bootstrap for the smooth trend minus the best constant
spanned `−0.000070` to `+0.000041`; zero was comfortably plausible.

No era-varying friendly coefficient was adopted. Both the opponent network and
the country venue state retain one friendly information ratio, `0.78621`.
This avoids adding a weak, unstable degree of freedom while prospective data
accumulate. Full candidate results are in `friendly-era-results.json` and
`venue-friendly-era-results.json`.

## Rolling temporal robustness

A second check repeatedly chose parameters using earlier completed blocks and
scored only the next block:

| Test block | Earlier-only selected model | Log-loss improvement |
| --- | --- | ---: |
| 1980–1999 | prior 60, static | 0.001431 |
| 2000–2009 | prior 55, static | 0.002630 |
| 2010–2019 | prior 60, 80-year half-life | 0.000980 |
| 2020–2026 | prior 60, 40-year half-life | 0.001410 |

Every outer block improved. The changing earlier-only selections also show why
the final parameters should be treated as a stable regularised region, not a
precisely known physical constant.

## Selected state and update

Let `d_i` be country `i`’s home-dependence state, `V_i` its posterior variance
and `h` the home sign from team one’s perspective.

For a home match:

```text
country correction = h × (d_1 + d_2) / 2
delta = era scale × (mu_1 - mu_2)
        + era home baseline × h
        + country correction
```

For a neutral match, both venue terms are zero.

Between observations:

```text
r = 2 ^ (-elapsed years / 40)
d_i(t) = r × d_i(t0)
V_i(t) = 60² - (60² - V_i(t0)) × r²
```

For each non-neutral observation, `z_i = h/2`,
`b = ln(10)/400`, result score is `S` and pre-match expected fractional score
is `E`:

```text
gradient_i  = q × b × z_i × (S - E)
curvature_i = q × b² × z_i² × E × (1 - E)
V_i'        = 1 / (1/V_i + sum(curvature_i))
d_i'        = d_i + V_i' × sum(gradient_i)
```

`q` is 1 for a competitive match and 0.78621 for an evidence-backed friendly.
Sums are over all of the country’s matches on the same complete date.

The main strength network uses the venue-adjusted expected result in its own
existing joint update. The country venue state itself does not use goal margin:
the unit-result rule beat the margin-weighted alternative in earlier-only
selection.

## End-to-end replay

After inserting the selected state into rating expectations, network updates,
the hidden score layer and annual calibration:

| Metric | Previous model | Country model | Improvement |
| --- | ---: | ---: | ---: |
| Final-layer log loss | 0.88016905 | **0.87833346** | **0.00183559** |
| Network-only log loss | 0.88151940 | **0.87992071** | **0.00159869** |
| Brier score | 0.51826591 | **0.51716153** | **0.00110438** |
| Ranked probability score | 0.17248005 | **0.17194856** | **0.00053149** |
| Most-likely W/D/L correct | 59.084% | **59.170%** | **0.085 pp** |

End-to-end log-loss changes by period:

| Period | Matches | Improvement |
| --- | ---: | ---: |
| 1960–1979 | 8,346 | 0.001420 |
| 1980–1999 | 12,881 | 0.001926 |
| 2000–2009 | 9,520 | 0.002838 |
| 2010–2019 | 9,734 | 0.001431 |
| 2020–2026 | 6,320 | 0.001315 |

Home matches improved by about `0.002533`. Competitive matches improved by
about `0.002172` and friendlies by about `0.001323`. Neutral matches receive
no direct venue correction; their end-to-end log loss changed by only
`+0.000046` because venue-adjusted non-neutral results slightly alter the
shared strength chronology.

A paired year-block bootstrap gave:

| Sample | 95% interval for improvement | Resamples better |
| --- | ---: | ---: |
| All 67 scored years | 0.001256–0.002447 | 100.0% |
| Untouched 2020–2026 | 0.000208–0.002607 | 99.0% |

## Ranking and historical guardrails

The improvement was not accepted on log loss alone. The full replay also had
to preserve sensible public rankings and historical records.

- Spain remained current No. 1, followed by Argentina.
- England remained sixth rather than being pushed upward by its unusually
  negative modern venue estimate.
- The leading all-time peaks remained Brazil and Spain.
- Only England represented pre-First World War football in the top ten
  national peaks; the release did not recreate the implausible early-British
  domination seen in rejected earlier models.
- Current top-ten ratings moved only modestly because the country term changes
  match expectations; it does not add points directly to public ratings.

## Interpreting country values

At the end of the audit replay, examples of large positive posterior means
included Bolivia, Sierra Leone, Libya and Equatorial Guinea. Examples of
negative means included Germany, Bahrain, Greece and England.

These are not rankings of atmosphere, supporters, travel difficulty or
national character. They are regularised residual result patterns after the
era baseline and opponent-network strength are accounted for. Standard errors
remain substantial, often around 45–55 points. Team pages therefore show:

- the full dependence estimate;
- its hosting half;
- its equal-and-opposite away half;
- neutral adjustment zero;
- standard error and 95% interval;
- non-neutral evidence count; and
- reliability relative to the 60-point prior.

The values revert toward zero when evidence becomes old. They should be read as
forecasting inputs with uncertainty, not permanent descriptive facts.

## Reproduction

`search_overlay.py` contains the causal screening evaluator. It expects the
numeric match ledger and baseline component export produced by the repository’s
audit evaluator. The production implementation is in
`scripts/venue_effects.py`, with frozen parameters in
`config/venue_effects.json`.

`search_friendly_era.py` and `search_venue_friendly_era.py` reproduce the two
friendly-era rejection tests.

Routine site refreshes do not reselect the structure, prior or half-life.
They replay the fixed formula and let each country state learn only from newly
completed results. A future refit requires a new dated audit and a new
untouched or prospective evaluation window.

## Limitations

- Country is a proxy for many unobserved mechanisms, including travel,
  altitude, climate, pitch familiarity and crowd conditions.
- The ledger does not provide reliable venue coordinates, travel distance,
  attendance, altitude, squad or kickoff-time covariates across all eras.
- Separate host and away mechanisms are not cleanly identified by the source
  ordering.
- Sparse teams have wide intervals even after hierarchical shrinkage.
- A fixed 40-year half-life is a practical regulariser, not a claim that venue
  culture changes at one universal physical rate.
- Retrospective improvement does not guarantee the same future gain.
  Prospective forecasts remain the final check.
