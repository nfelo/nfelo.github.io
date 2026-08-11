# Global club ratings

The Global Clubs section is an independent senior men’s club model. It does not
reuse the national-team state, covariance, parameters or rankings.

## Canonical match ledger

The unattended build combines five machine-readable source families:

- `schochastics/football-data` supplies the broad historical top-division and
  continental backbone.
- `engsoccerdata` adds English tiers 2–8, Scottish lower tiers, Germany tier 2,
  domestic cups, playoffs and European competition metadata.
- the current `dcaribou/transfermarkt-datasets` feed adds stable modern match,
  competition, round and club identifiers.
- `BrazilianFootball/Data` adds CBF-report-derived Série A–D and Copa do Brasil
  results for 2013–2025. A compact, hash-manifested snapshot is stored in this
  repository and refreshed during the existing weekly full source pass.
- `FerrerasRP/FootballData` adds fourteen CC0 Brazilian state championships
  for 2019–2026. Its 112 JSON files are schema-checked and compacted into a
  second hash-manifested repository snapshot.

The source directory supplied by the site owner at
<https://docs.ufpr.br/~mmsabino/sstatistics/fontes_pesquisa.html> is retained as
a discovery and corroboration index. Its many historical pages are not scraped
by the scheduled build because their formats and identifiers are not stable
enough for a fail-closed replay.

Every candidate match is normalised to a common schema, including date, clubs,
score, competition, competition kind, tiers, venue, cross-border status,
duration, leg, round, source and source-row reference. Overlap is removed only
after club identity resolution. The richer source wins an exact duplicate, but
its original source reference remains public.

Club identity resolution is deliberately conservative:

1. stable source identities, with federation-state scoping where names collide;
2. exact and normalised same-country labels when they are unambiguous;
3. a fixture fingerprint only when the name evidence, coverage and winning
   candidate margin all pass fixed thresholds;
4. a short, reviewed, country-scoped alias table for long/short forms; and
5. explicit separation when legal or sporting succession is ambiguous.

This prevents a similarly named lower-tier club from inheriting a major club’s
history. It also avoids blanket corporate-suffix merging: Wimbledon and AFC
Wimbledon, for example, remain different identities.

## Hierarchical Elo state

Each club has a residual strength and each domestic association has a shared
coefficient:

```text
mean_i = 1500 + club_residual_i + association_coefficient_i
rating_i = mean_i - uncertainty_penalty × standard_error_i
```

Domestic matches move the two club residuals. Cross-border matches split their
update between club residuals and association coefficients. This is the bridge
between league systems that otherwise have no common opponents.

The public table ranks the uncertainty-adjusted `rating`; forecasts use the
latent `mean`. Evidence decays with time, and club plus association prior
uncertainty is retained separately. New, sparse or inward-looking clubs are
therefore ranked cautiously even when their estimated mean is high.

The result update uses a fitted K factor, a logarithmic goal-margin multiplier,
competition-kind weight and duration weight. Penalty-shootout decisions are
learned as match draws, not as ordinary goal margin. Season regression pulls a
club toward the prior for its latest known tier. Association coefficients
regress more slowly.

## Home, away and probabilities

A match forecast uses:

```text
difference = home_mean - away_mean + venue_adjustment
expected_home_score = 1 / (1 + 10 ^ (-difference / 400))
draw = draw_peak × 4 × expected_home_score × (1 - expected_home_score)
home_win = expected_home_score - draw / 2
away_win = 1 - expected_home_score - draw / 2
```

Domestic and cross-border home advantages are fitted separately. Neutral
matches receive zero. Swapping the clubs and reversing the venue swaps home and
away probabilities.

All matches on one complete date are forecast from a single frozen
start-of-day state. Only after every probability for that date has been stored
are its results combined into an update. The probabilities are therefore
pre-match and invariant to same-date input order.

## Aggregate-aware two-leg ties

Explicit first and second legs are paired before rating. A second leg receives
full weight when:

- the aggregate is level before or after it;
- the aggregate leader confirms its advantage by winning or drawing the leg;
- the match reverses which club leads the tie; or
- the source does not identify a reliable tie.

Only a controlled loss by the club that remains ahead on aggregate is
discounted. For that case:

```text
leverage = max(exp(-abs(aggregate_before) / scale),
               exp(-abs(aggregate_after) / scale))
weight = floor + (1 - floor) × leverage
```

The selected floor is `0.10` and the scale is `1.0` goal. If a club wins the
first leg 4–0 and accepts a 0–1 second-leg loss, the latter retains about 14.5%
of ordinary information. The 4–1 aggregate superiority is preserved, while the
second result is not erased.

The aggregate values are always stored from that row’s home-club perspective,
along with the final leg weight and total evidence weight.

## Coefficient selection and frozen release

The club coefficients were selected with a chronological coordinate-grid
bake-off. The replay warms up from 2000, selects ordinary coefficients on
2018–2022 log loss, and reports 2023 onward as an untouched test window.
Aggregate floor and scale are selected only on matches played within 120 days
after a controlled-loss second leg, which tests whether the adjusted rating
state improves subsequent prediction rather than rewarding an in-sample story
about the leg itself.

The exact selected constants and validation counts are stored in
`config/club_model.json`. Routine source refreshes replay those constants and do
not refit them. Any future coefficient change must be an explicit reviewed
methodology release.

## Publication schema

The static build writes:

- current club and association rankings;
- active and historical club catalogs;
- one year-opening ranking file per year;
- one complete match archive file per calendar year;
- one compact annual trajectory and match-year index per club;
- competition coverage, peaks, strongest matches, upsets, aggregate examples
  and year-opening number ones;
- full source manifests, build-time hashes, licences and limitations; and
- all fitted coefficients and validation metadata.

Large match files use an array schema published in `data/meta.json` and
`data/matches/index.json`. This keeps the complete archive practical on static
GitHub Pages while preserving every field needed by the browser.

## Limitations

Coverage is broad rather than literally complete. Lower tiers, state leagues,
early domestic cups and some confederations are uneven. Mutable source feeds
can publish historical corrections; their downloaded bytes and SHA-256 hashes
are recorded for each build. Identity evidence can also improve. Either change
can alter a later replay without changing the frozen coefficients.

Ratings are comparative estimates, not official classifications or betting
advice.
